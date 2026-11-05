"""Streamlit UI:  streamlit run querypilot/ui.py"""
import pandas as pd
import streamlit as st

from querypilot.graph import QueryPilot
from querypilot.llm import get_llm

st.set_page_config(page_title="QueryPilot", page_icon=None, layout="wide")
st.title("QueryPilot")
st.caption("Ask a question about the e-commerce warehouse. Generated SQL is validated by AST guardrails before it runs.")


@st.cache_resource
def pilot() -> QueryPilot:
    return QueryPilot(get_llm())


examples = ["What is total revenue by product category?", "Which state generated the most revenue?",
            "What was month-over-month change in order count during 2025?", "Average delivery time per carrier?"]
q = st.text_input("Question", placeholder=examples[0])
cols = st.columns(len(examples))
for c, ex in zip(cols, examples):
    if c.button(ex, use_container_width=True):
        q = ex

if q:
    with st.spinner("Thinking..."):
        s = pilot().ask(q)
    if s.get("status") == "ok":
        st.success(s.get("answer") or "Done")
        df = pd.DataFrame(s["rows"], columns=s["columns"])
        st.dataframe(df, use_container_width=True)
        if len(df.columns) == 2 and 1 < len(df) <= 50 and pd.api.types.is_numeric_dtype(df.iloc[:, 1]):
            st.bar_chart(df.set_index(df.columns[0]))
    else:
        st.error(s.get("answer"))
    with st.expander("SQL and agent trace"):
        st.code(s.get("safe_sql") or s.get("sql") or "", language="sql")
        st.json(s.get("trace", []))
        st.caption(f"attempts: {s.get('attempts')} | tables: {', '.join(s.get('tables', []))} | {s.get('latency_ms')} ms")
