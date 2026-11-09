"""Chat backends: Groq (free tier, native tool calling), Ollama (local, JSON replies) or a scripted stub for tests.

Every backend returns the agent's format: '{"tool": name, "args": {...}}' or '{"final": {...}}'."""
import json
import os
import time

import requests


def tool_specs():
    """The agent's tools, declared for native tool calling. final_answer carries the answer."""
    from triage.agent import CATEGORIES

    def fn(name, desc, props=None, required=None):
        return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
            "type": "object", "properties": props or {}, "required": required or []}}}
    return [
        fn("job_record", "The job's key attributes: status, hold reason, exit code, memory request and use, files."),
        fn("read_file", "Numbered lines of one of the job's files.",
           {"name": {"type": "string", "enum": ["job.log", "stdout.txt", "stderr.txt"]},
            "start": {"type": "integer"}, "count": {"type": "integer"}}, ["name"]),
        fn("search", "Case-insensitive search across the job's record and files.", {"pattern": {"type": "string"}}, ["pattern"]),
        fn("search_docs", "HTCondor documentation snippets.", {"query": {"type": "string"}}, ["query"]),
        fn("request_action", "Ask a human operator to run a command. Nothing runs without approval.",
           {"command": {"type": "string"}, "reason": {"type": "string"}}, ["command", "reason"]),
        fn("final_answer", "Give the final answer once you know the cause.",
           {"category": {"type": "string", "enum": CATEGORIES}, "summary": {"type": "string"},
            "claims": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}}},
                "required": ["text", "evidence"]}},
            "fix": {"type": "string"}}, ["category", "summary", "claims", "fix"]),
    ]


def as_agent_json(name, args):
    """Translate a native tool call into the agent's reply format (also tolerates the two formats mixed)."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    args = args if isinstance(args, dict) else {}
    if "tool" in args:                                   # model wrapped the agent's JSON inside a tool call
        return json.dumps({"tool": args["tool"], "args": args.get("args") or {}})
    if "final" in args:
        return json.dumps({"final": args["final"]})
    if name in ("final_answer", "final"):
        return json.dumps({"final": args})
    if not name:
        return ""                                        # no tool named: not a valid reply
    return json.dumps({"tool": name, "args": args})


class LLM:
    def __init__(self, backend=None, model=None, script=None):
        self.backend = backend or os.environ.get("LLM_BACKEND", "groq")
        self.model = model or os.environ.get("LLM_MODEL") or {"groq": "openai/gpt-oss-20b",
                                                                "ollama": "llama3.1"}.get(self.backend, "stub")
        self.script = list(script or [])          # stub: replies returned in order
        self.native_tools = True

    def chat(self, messages):
        """Returns (reply in the agent's format, tokens used)."""
        if self.backend == "stub":
            return (self.script.pop(0) if self.script else
                    '{"final": {"category": "other", "summary": "stub", "claims": [], "fix": ""}}'), 0
        if self.backend == "ollama":
            r = requests.post(os.environ.get("OLLAMA_URL", "http://localhost:11434") + "/api/chat",
                              json={"model": self.model, "messages": messages, "stream": False, "format": "json",
                                    "options": {"temperature": 0}}, timeout=300)
            r.raise_for_status()
            j = r.json()
            return j["message"]["content"], j.get("prompt_eval_count", 0) + j.get("eval_count", 0)
        return self._groq(messages)

    def _groq(self, messages):
        key = os.environ.get("GROQ_API_KEY", "")
        if not key:
            raise RuntimeError("Set GROQ_API_KEY (free at console.groq.com), or use LLM_BACKEND=ollama.")
        for _ in range(6):
            body = {"model": self.model, "messages": messages, "temperature": 0}
            if self.native_tools:
                body.update(tools=tool_specs(), tool_choice="required")
            else:
                body["response_format"] = {"type": "json_object"}
            r = requests.post("https://api.groq.com/openai/v1/chat/completions", json=body, timeout=120,
                              headers={"Authorization": f"Bearer {key}"})
            if r.status_code == 429:                       # free-tier rate limit: wait and retry
                time.sleep(float(r.headers.get("retry-after", 10)))
                continue
            if r.status_code == 400:
                err = (r.json().get("error") or {}) if r.headers.get("content-type", "").startswith("application/json") else {}
                if err.get("code") == "tool_use_failed" and err.get("failed_generation"):
                    try:                                    # the model's intended call is in the error: use it
                        gen = json.loads(err["failed_generation"])
                        return as_agent_json(gen.get("name", ""), gen.get("arguments", {})), 0
                    except (json.JSONDecodeError, AttributeError):
                        pass
                if err.get("code") in ("tool_use_failed", "output_parse_failed"):   # empty or unparseable generation: nudge and retry
                    messages = messages + [{"role": "user", "content": "Reply only by calling one of the provided tools. Call final_answer once you have enough evidence."}]
                    continue
                if self.native_tools and "tool" in r.text.lower() and err.get("code") != "tool_use_failed":
                    self.native_tools = False               # model without tool support: plain JSON replies
                    continue
            if not r.ok:
                hint = (f" Groq does not recognise the model '{self.model}': set LLM_MODEL to one listed at "
                        "console.groq.com/docs/models." if r.status_code == 404 else "")
                raise RuntimeError(f"Groq error {r.status_code}: {r.text[:300]}{hint}")
            j = r.json()
            msg = j["choices"][0]["message"]
            used = j.get("usage", {}).get("total_tokens", 0)
            calls = msg.get("tool_calls") or []
            if calls:
                f = calls[0]["function"]
                return as_agent_json(f.get("name", ""), f.get("arguments", "{}")), used
            return msg.get("content") or "", used
        raise RuntimeError("Groq kept rate-limiting; wait a minute and run again.")
