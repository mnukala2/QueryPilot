"""LangGraph multi-agent pipeline: retrieve schema -> generate SQL -> guardrails -> execute -> self-repair -> answer."""
from __future__ import annotations

import re
import time
from typing import Any, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from . import prompts
from .config import settings
from .executor import Executor
from .guardrails import validate
from .retrieval import SchemaRetriever
from .schema import full_schema, render

_SCHEMA_ERRORS = ("does not have a column", "not found", "Referenced column", "Table with name", "Binder Error")


class QPState(TypedDict, total=False):
    question: str
    tables: list[str]
    schema: str
    messages: list[Any]
    sql: str
    safe_sql: str
    error: str | None
    error_kind: str | None  # guardrail | execution
    attempts: int
    first_pass_ok: bool
    columns: list[str]
    rows: list[tuple]
    answer: str
    prompt_tokens: int
    completion_tokens: int
    trace: list[dict]
    status: str  # ok | failed | cannot_answer


def extract_sql(text: str) -> str:
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return (m.group(1) if m else text).strip().rstrip(";").strip()


def _usage(msg: AIMessage) -> tuple[int, int]:
    u = getattr(msg, "usage_metadata", None) or {}
    return int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0))


class QueryPilot:
    def __init__(self, llm: BaseChatModel, executor: Executor | None = None, retriever: SchemaRetriever | None = None,
                 max_repairs: int | None = None, answer: bool = True, use_retrieval: bool = True):
        self.llm = llm
        self.executor = executor or Executor()
        self.retriever = retriever or SchemaRetriever(top_k=settings.top_k_tables)
        self.max_repairs = settings.max_repairs if max_repairs is None else max_repairs
        self.answer_enabled = answer
        self.use_retrieval = use_retrieval
        self.graph = self._build()

    # ---------------- nodes ----------------
    def retrieve(self, s: QPState) -> QPState:
        t0 = time.perf_counter()
        if self.use_retrieval:
            tables = self.retriever.retrieve(s["question"]).tables
            schema = render(tables)
        else:
            tables, schema = [], full_schema()
        return {"tables": tables, "schema": schema, "attempts": 0, "prompt_tokens": 0, "completion_tokens": 0,
                "trace": [{"node": "retrieve", "tables": tables, "ms": round((time.perf_counter() - t0) * 1000, 2)}]}

    def generate(self, s: QPState) -> QPState:
        t0 = time.perf_counter()
        attempts = s.get("attempts", 0)
        schema = s["schema"]
        if attempts and s.get("error") and any(k in s["error"] for k in _SCHEMA_ERRORS):
            schema = full_schema()  # widen context when retrieval may have missed a table/column
        if attempts == 0:
            msgs = [SystemMessage(prompts.GENERATOR_SYSTEM.format(schema=schema)), HumanMessage(s["question"])]
        else:
            msgs = list(s["messages"])
            msgs[0] = SystemMessage(prompts.GENERATOR_SYSTEM.format(schema=schema))
            msgs.append(HumanMessage(prompts.REPAIR_USER.format(sql=s.get("sql", ""), error=s["error"], question=s["question"])))
        reply = self.llm.invoke(msgs)
        pt, ct = _usage(reply)
        text = reply.content if isinstance(reply.content, str) else str(reply.content)
        sql = extract_sql(text)
        trace = s["trace"] + [{"node": "generate", "attempt": attempts, "sql": sql, "ms": round((time.perf_counter() - t0) * 1000, 2)}]
        out: QPState = {"messages": msgs + [AIMessage(text)], "sql": sql, "attempts": attempts + 1, "trace": trace,
                        "prompt_tokens": s.get("prompt_tokens", 0) + pt, "completion_tokens": s.get("completion_tokens", 0) + ct}
        if sql.strip().upper().startswith("CANNOT_ANSWER"):
            out.update(status="cannot_answer", answer="That question can't be answered from the available data.")
        return out

    def guard(self, s: QPState) -> QPState:
        g = validate(s["sql"], max_rows=settings.max_rows)
        trace = s["trace"] + [{"node": "guardrails", "ok": g.ok, "reason": g.reason}]
        if g.ok:
            return {"safe_sql": g.sql, "error": None, "error_kind": None, "trace": trace}
        return {"error": f"Guardrail rejected the query: {g.reason}", "error_kind": "guardrail", "trace": trace}

    def execute(self, s: QPState) -> QPState:
        r = self.executor.run(s["safe_sql"])
        trace = s["trace"] + [{"node": "execute", "ok": r.ok, "rows": len(r.rows), "error": r.error, "ms": round(r.ms, 2)}]
        out: QPState = {"trace": trace}
        if s.get("attempts") == 1:
            out["first_pass_ok"] = r.ok
        if r.ok:
            out.update(columns=r.columns, rows=r.rows, error=None, error_kind=None, status="ok")
        else:
            out.update(error=r.error, error_kind="execution")
        return out

    def answer(self, s: QPState) -> QPState:
        if not self.answer_enabled:
            return {}
        msgs = [SystemMessage(prompts.ANSWER_SYSTEM),
                HumanMessage(prompts.ANSWER_USER.format(question=s["question"], sql=s["safe_sql"], columns=s["columns"], rows=s["rows"][:20]))]
        reply = self.llm.invoke(msgs)
        pt, ct = _usage(reply)
        return {"answer": reply.content if isinstance(reply.content, str) else str(reply.content),
                "prompt_tokens": s.get("prompt_tokens", 0) + pt, "completion_tokens": s.get("completion_tokens", 0) + ct,
                "trace": s["trace"] + [{"node": "answer"}]}

    def fail(self, s: QPState) -> QPState:
        return {"status": "failed", "answer": f"Could not produce a valid query: {s.get('error')}"}

    # ---------------- routing ----------------
    def _after_generate(self, s: QPState) -> str:
        return END if s.get("status") == "cannot_answer" else "guard"

    def _after_guard(self, s: QPState) -> str:
        if not s.get("error"):
            return "execute"
        return "generate" if s["attempts"] <= self.max_repairs else "fail"

    def _after_execute(self, s: QPState) -> str:
        if not s.get("error"):
            return "answer"
        return "generate" if s["attempts"] <= self.max_repairs else "fail"

    def _build(self):
        g = StateGraph(QPState)
        for name in ("retrieve", "generate", "guard", "execute", "answer", "fail"):
            g.add_node(name, getattr(self, name))
        g.set_entry_point("retrieve")
        g.add_edge("retrieve", "generate")
        g.add_conditional_edges("generate", self._after_generate, {"guard": "guard", END: END})
        g.add_conditional_edges("guard", self._after_guard, {"execute": "execute", "generate": "generate", "fail": "fail"})
        g.add_conditional_edges("execute", self._after_execute, {"answer": "answer", "generate": "generate", "fail": "fail"})
        g.add_edge("answer", END)
        g.add_edge("fail", END)
        return g.compile()

    def ask(self, question: str) -> QPState:
        t0 = time.perf_counter()
        state = self.graph.invoke({"question": question}, config={"recursion_limit": 25})
        state["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        state.setdefault("first_pass_ok", False)
        return state
