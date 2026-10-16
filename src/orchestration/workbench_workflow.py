"""The actual workbench LangGraph: evidence, safety, draft, verification and audit."""

from __future__ import annotations

import time
import uuid
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from src.agents.assist_agent import AssistAgent
from src.data.contest_data import ContestDataStore
from src.ops.case_store import CaseStore, now

LEVELS = {"低": "low", "中": "medium", "高": "high", "紧急": "critical"}


class AssistState(TypedDict, total=False):
    """One invocation's state; never shared between customer sessions."""

    session_id: str
    message: str
    point: str | None
    mode: str
    context: dict
    signals: dict
    analysis_id: str
    result: dict
    task_ids: list[str]
    trace: list[dict]
    prepared: bool


class WorkbenchWorkflow:
    """Use explicit nodes; urgent tasks are emitted before optional model generation."""

    def __init__(
        self, data: ContestDataStore, agent: AssistAgent, cases: CaseStore,
        emit: Callable[[dict], None],
    ) -> None:
        self.data, self.agent, self.cases, self.emit = data, agent, cases, emit
        graph = StateGraph(AssistState)
        for name, function in [
            ("evidence", self.evidence), ("safety", self.safety),
            ("draft", self.draft), ("verify", self.verify), ("audit", self.audit),
        ]:
            graph.add_node(name, function)
        graph.add_edge(START, "evidence")
        graph.add_edge("evidence", "safety")
        graph.add_edge("safety", "draft")
        graph.add_edge("draft", "verify")
        graph.add_edge("verify", "audit")
        graph.add_edge("audit", END)
        self.graph = graph.compile()

    @staticmethod
    def _trace(state: AssistState, node: str, started: float) -> list[dict]:
        return state.get("trace", []) + [{
            "node": node, "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }]

    def evidence(self, state: AssistState) -> dict:
        if state.get("prepared"):
            return {}
        started = time.perf_counter()
        context = self.data.get_session(
            state["session_id"], before_message_id=state.get("point"),
            analysis_mode=state["mode"],
        )
        if not context["messages"]:
            raise KeyError(state["session_id"])
        identity = self.cases.consumer_identity(state["session_id"])
        context = self.data.with_service_history(context, identity)
        message = state["message"] or context["latest_buyer_message"]
        if state["mode"] == "snapshot":
            # User-entered demo turns are stored separately from contest history.
            # Only the same selected point can reuse them; replay never does.
            prior = self.cases.recent_analyses(state["session_id"], limit=50)
            context["runtime_inputs"] = [
                {"message_id": row["analysis_id"], "message_text": row["input_message"],
                 "角色": "买家", "session_id": state["session_id"],
                 "发送时间": row["created_at"], "analysis_point": row["analysis_point"]}
                for row in reversed(prior)
                if row.get("analysis_mode") == "snapshot" and row.get("input_message")
                and row.get("input_is_override") and row.get("analysis_point") == context["analysis_point"]
            ]
            # Repeated submission of the current turn is a retry, not a new
            # historical turn. Preserve earlier distinct turns (including A-B-A).
            while context["runtime_inputs"] and context["runtime_inputs"][-1]["message_text"] == message:
                context["runtime_inputs"].pop()
        return {"context": context, "message": message,
                "trace": self._trace(state, "evidence", started)}

    def safety(self, state: AssistState) -> dict:
        if state.get("prepared"):
            return {}
        started = time.perf_counter()
        signals = self.agent.inspect(
            state["context"], state["message"], state["session_id"], state["analysis_id"],
        )
        tasks = []
        for alert in signals["rule_alerts"]:
            task = self.cases.create_task(
                state["session_id"], alert["name"], alert["action"],
                priority=alert["level"], risk_code=alert["code"],
                analysis_id=state["analysis_id"], actor="风险节点",
            )
            tasks.append(task["task_id"])
            self.emit({"session_id": state["session_id"], "task_id": task["task_id"],
                       "name": alert["name"], "level": alert["level"],
                       "time": task["updated_at"], "phase": "safety"})
        return {"signals": signals, "task_ids": tasks,
                "trace": self._trace(state, "safety", started)}

    def draft(self, state: AssistState) -> dict:
        started = time.perf_counter()
        result = self.agent.assist(
            state["context"], state["message"], session_id=state["session_id"],
            analysis_id=state["analysis_id"], signals=state["signals"],
        )
        return {"result": result, "trace": self._trace(state, "draft", started)}

    def verify(self, state: AssistState) -> dict:
        started = time.perf_counter()
        result = dict(state["result"])
        priority = LEVELS[result["risk_level"]]
        tasks = state["task_ids"][:]
        if priority in {"high", "critical"} and not any(
            self.cases.get_task(task_id)["priority"] in {"high", "critical"}
            for task_id in tasks
        ):
            task = self.cases.create_task(
                state["session_id"], "风险人工复核", result["next_action"],
                priority=priority, risk_code="model_review", analysis_id=state["analysis_id"],
                actor="校验节点",
            )
            tasks.append(task["task_id"])
        result.update(
            task_ids=tasks, analysis_point=state["context"]["analysis_point"],
            evidence=state["context"]["evidence"],
            basis_warning=state["context"]["basis_warning"],
            created_at=now(),
            service_history=state["context"]["service_history"],
            input_message=state["message"],
            input_is_override=state["message"] != state["context"]["latest_buyer_message"],
        )
        return {"result": result, "trace": self._trace(state, "verify", started)}

    def audit(self, state: AssistState) -> dict:
        started = time.perf_counter()
        result = dict(state["result"])
        result["trace"] = self._trace(state, "audit", started)
        result["latency_ms"] = round(sum(node["duration_ms"] for node in result["trace"]), 2)
        self.cases.record_analysis(result)
        self.emit({"session_id": state["session_id"], "analysis_id": result["analysis_id"],
                   "phase": "completed"})
        return {"result": result}

    def run(self, session_id: str, message: str = "", point: str | None = None, mode: str = "snapshot") -> dict:
        """Run a bounded assistance request; returns evidence and execution trace."""
        return self.graph.invoke({
            "session_id": session_id, "message": message, "point": point, "mode": mode,
            "analysis_id": str(uuid.uuid4()), "trace": [],
        })["result"]

    def prepare(self, session_id: str, message: str, point: str | None, mode: str) -> AssistState:
        """Run evidence/safety before waiting for a scarce inference slot."""
        state: AssistState = {
            "session_id": session_id, "message": message, "point": point, "mode": mode,
            "analysis_id": str(uuid.uuid4()), "trace": [],
        }
        state.update(self.evidence(state))
        state.update(self.safety(state))
        state["prepared"] = True
        return state

    def run_prepared(self, state: AssistState) -> dict:
        """Continue the same node flow using a bounded, already-inspected context."""
        return self.graph.invoke(state)["result"]

    def record_rejection(self, state: AssistState, reason: str) -> dict:
        """Preserve safety provenance when the inference queue rejects admission."""
        result = self.agent._fallback(
            state["context"], state["message"], state["signals"], reason)
        result.update(
            model_status="queue_full", task_ids=state["task_ids"],
            trace=state["trace"] + [{"node": "queue_rejected", "duration_ms": 0}],
            created_at=now(), analysis_point=state["context"]["analysis_point"],
            service_history=state["context"]["service_history"],
            evidence=state["context"]["evidence"],
            basis_warning=state["context"]["basis_warning"],
        )
        self.cases.record_analysis(result)
        return result
