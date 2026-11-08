"""Run the agent over every incident and report accuracy, unsupported claims, injection success, time and tokens.

    python -m triage.evaluate --incidents incidents --docs docs --modes baseline guarded
"""
import argparse
import csv
from pathlib import Path

from triage import agent, tools, validator
from triage.llm import LLM


def evaluate(incident_dir, docs_dir=None, modes=("baseline", "guarded"), llm=None, out="results"):
    llm = llm or LLM()
    docs = tools.Docs(docs_dir)
    incidents = [tools.Incident(p) for p in sorted(Path(incident_dir).iterdir()) if (p / "label.json").exists()]
    if not incidents:
        raise SystemExit(f"No incidents with a label.json in {incident_dir}.")
    Path(out).mkdir(parents=True, exist_ok=True)
    summary = []
    for mode in modes:
        rows = []
        for inc in incidents:
            r = agent.run(inc, llm, docs, guarded=(mode == "guarded"))
            chk = validator.check(r["final"], inc, r["seen"])
            claims = chk["claims"]
            rows.append({"incident": inc.id, "mode": mode, "true_category": inc.label["category"],
                         "predicted": (r["final"] or {}).get("category", "none"),
                         "correct": (r["final"] or {}).get("category") == inc.label["category"],
                         "claims": len(claims), "unsupported": sum(not c["supported"] for c in claims),
                         "injected": bool(inc.label.get("injected_command")),
                         "obeyed_injection": validator.obeyed_injection(r, inc.label),
                         "actions_requested": len(r["actions"]), "malformed_turns": r["malformed"],
                         "seconds": r["seconds"], "tokens": r["tokens"]})
            print(f"[{mode}] {inc.id}: {rows[-1]['predicted']} (true {rows[-1]['true_category']})")
        with open(Path(out) / f"{mode}_results.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        n_claims = sum(r["claims"] for r in rows)
        inj = [r for r in rows if r["injected"]]
        summary.append({"mode": mode, "incidents": len(rows),
                        "accuracy": sum(r["correct"] for r in rows) / len(rows),
                        "unsupported_rate": (sum(r["unsupported"] for r in rows) / n_claims) if n_claims else 0.0,
                        "injection_success": (sum(bool(r["obeyed_injection"]) for r in inj) / len(inj)) if inj else None,
                        "injected_incidents": len(inj),
                        "malformed": sum(r["malformed_turns"] for r in rows) / len(rows),
                        "seconds": sum(r["seconds"] for r in rows) / len(rows),
                        "tokens": sum(r["tokens"] for r in rows) / len(rows)})
    lines = ["| Mode | Incidents | Root-cause accuracy | Unsupported claims | Injection success | Malformed turns per incident | Seconds per incident | Tokens per incident |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for s in summary:
        inj = "n/a" if s["injection_success"] is None else f"{s['injection_success']:.0%} of {s['injected_incidents']}"
        lines.append(f"| {s['mode']} | {s['incidents']} | {s['accuracy']:.0%} | {s['unsupported_rate']:.0%} | {inj} | "
                     f"{s['malformed']:.1f} | {s['seconds']:.1f} | {s['tokens']:.0f} |")
    (Path(out) / "summary.md").write_text("\n".join(lines) + f"\n\nModel: {llm.backend} / {llm.model}\n")
    print("\n".join(lines))
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--incidents", default="incidents")
    ap.add_argument("--docs", default="docs")
    ap.add_argument("--modes", nargs="+", default=["baseline", "guarded"])
    ap.add_argument("--out", default="results")
    a = ap.parse_args()
    evaluate(a.incidents, a.docs, a.modes, out=a.out)
