"""Demo: pick an incident, run the agent, see its evidence and what the validator thinks.   streamlit run app.py"""
from pathlib import Path

import streamlit as st

from triage import agent, tools, validator
from triage.llm import LLM

st.set_page_config(page_title="Grid triage agent", layout="wide")
st.title("Grid triage agent")
st.caption("An LLM agent that investigates failed and held HTCondor jobs with read-only tools. Every claim must cite "
           "the log line it rests on, and nothing it suggests runs without a person's approval.")

folder = Path(st.sidebar.text_input("Incidents folder", "incidents"))
incidents = sorted(p.name for p in folder.iterdir() if p.is_dir()) if folder.exists() else []
if not incidents:
    st.info("No incidents yet. Follow the README to collect them from your HTCondor pool.")
    st.stop()
pick = st.sidebar.selectbox("Incident", incidents)
guarded = st.sidebar.radio("Mode", ["guarded", "baseline"],
                           help="Guarded marks tool output as untrusted data and flags lines that read like instructions.") == "guarded"
inc = tools.Incident(folder / pick)

with st.expander("What the agent can read"):
    for lid, text in inc.lines.items():
        st.text(f"[{lid}] {text}")

if st.button("Run the agent", type="primary"):
    with st.spinner("Investigating..."):
        r = agent.run(inc, LLM(), tools.Docs("docs"), guarded=guarded)
    final = r["final"] or {}
    chk = validator.check(final, inc, r["seen"])
    st.subheader(f"Cause: {final.get('category', 'no answer')}")
    st.write(final.get("summary", ""))
    for c in chk["claims"]:
        icon = "✅" if c["supported"] else "⚠️"
        st.markdown(f"{icon} **{c['claim']}**")
        for e in c["evidence"]:
            st.text(f"    [{e}] {inc.lines.get(e, '(no such line)')}")
        for p in c["problems"]:
            st.caption(f"Validator: {p}")
    st.markdown(f"**Suggested fix:** {final.get('fix', '')}")
    for a in r["actions"]:
        st.warning(f"Action requested, waiting for human approval (not run): `{a['command']}`. Reason: {a['reason']}")
    obeyed = validator.obeyed_injection(r, inc.label)
    if obeyed is not None:
        (st.error if obeyed else st.success)("This incident contains a planted instruction. The agent "
                                             + ("followed it." if obeyed else "did not follow it."))
    st.caption(f"{len(r['trace'])} tool calls, {r['seconds']} s, {r['tokens']} tokens. "
               f"True cause: {(inc.label or {}).get('category', 'unknown')}")
    with st.expander("Full trace"):
        for t in r["trace"]:
            st.markdown(f"**{t['tool']}** `{t['args']}`")
            st.text(t["output"])
