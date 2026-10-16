"""Flask chat and risk-dashboard application factory."""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from src.agents.emotion_agent import EmotionAgent
from src.agents.intent_agent import IntentAgent
from src.agents.knowledge_agent import KnowledgeAgent
from src.agents.response_agent import ResponseAgent
from src.agents.risk_agent import RiskAgent
from src.agents.assist_agent import AssistAgent
from src.api.websocket_handler import init_socketio, record_result, socketio
from src.data.contest_data import ContestDataStore
from src.models.qwen_wrapper import configured_model, is_loopback_url
from src.ops.case_store import CaseStore, now
from src.orchestration.langgraph_workflow import CustomerServiceWorkflow
from src.orchestration.workbench_workflow import WorkbenchWorkflow
from src.orchestration.analysis_jobs import AnalysisJobs, QueueFull
from src.optimization.smart_cache import SmartCache
from evaluation.evaluation_center import (
    DEFAULT_DB,
    EfficiencyStudyAgent,
    FrozenAnnotationAgent,
    _normalize_context,
)

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]


def create_app(
    workflow: CustomerServiceWorkflow | None = None,
    contest_store: ContestDataStore | None = None,
    assist_agent: AssistAgent | None = None,
    case_store: CaseStore | None = None,
    evaluation_store: FrozenAnnotationAgent | None = None,
) -> Flask:
    """Construct application with overridable workflow for tests."""
    load_dotenv(ROOT / ".env")
    app = Flask(
        __name__, template_folder=str(ROOT / "frontend" / "templates"),
        static_folder=str(ROOT / "frontend" / "static"),
    )
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY") or os.urandom(32)
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024
    init_socketio(app)
    default_contest_dir = ROOT / "data" / "contest"
    contest_store = contest_store or (
        ContestDataStore(default_contest_dir) if (default_contest_dir / "聊天记录.json").exists() else None
    )
    app.extensions["contest_store"] = contest_store
    app.extensions["assist_agent"] = assist_agent or AssistAgent()
    app.extensions["case_store"] = case_store or CaseStore(
        os.getenv("CASE_DB_PATH", str(ROOT / "data" / "runtime" / "cases.sqlite")))
    app.extensions["evaluation_store"] = evaluation_store or FrozenAnnotationAgent(
        os.getenv("EVALUATION_DB_PATH", str(DEFAULT_DB)))
    app.extensions["efficiency_agent"] = EfficiencyStudyAgent(
        app.extensions["evaluation_store"])
    app.extensions["analysis_jobs"] = AnalysisJobs()
    if contest_store:
        app.extensions["workbench_workflow"] = WorkbenchWorkflow(
            contest_store, app.extensions["assist_agent"], app.extensions["case_store"],
            lambda event: socketio.emit("assist_update", event),
        )
    app.extensions["workflow"] = workflow or CustomerServiceWorkflow(
        IntentAgent(), EmotionAgent(), KnowledgeAgent(), ResponseAgent(), RiskAgent()
    )

    @app.post("/chat")
    def chat() -> tuple:
        """Process a bounded JSON query; no user identifiers in logs or alerts."""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Expected JSON object"), 400
        query = payload.get("message")
        profile = payload.get("user_profile", {})
        if profile is None:
            profile = {}
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 2000:
            return jsonify(error="message must contain 1-2000 characters"), 400
        if not isinstance(profile, dict):
            return jsonify(error="user_profile must be an object"), 400
        if not isinstance(profile.get("history", {}), dict):
            return jsonify(error="user_profile.history must be an object"), 400
        if not isinstance(profile.get("emotion_history", []), list):
            return jsonify(error="user_profile.emotion_history must be an array"), 400
        history = profile.get("history", {})
        for field in ("refund_count_30d", "repeat_contact_7d", "complaint_count", "avg_satisfaction"):
            value = history.get(field)
            if value is None:
                history[field] = 5.0 if field == "avg_satisfaction" else 0
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not 0 <= value <= 100):
                return jsonify(error=f"user_profile.history.{field} must be a number from 0 to 100"), 400
        if any(not isinstance(item, dict) or not isinstance(item.get("valence", 0), (int, float))
               for item in profile.get("emotion_history", [])):
            return jsonify(error="invalid emotion_history entry"), 400
        session_id = str(payload.get("session_id") or uuid.uuid4())[:128]
        result = app.extensions["workflow"].run(query.strip(), profile, session_id)
        metadata = result["metadata"]
        cases = app.extensions["case_store"]
        analysis_id = str(uuid.uuid4())
        task_ids = []
        for alert in metadata["alerts"]:
            task = cases.create_task(
                session_id, alert["name"], alert["action"], priority=alert["level"],
                analysis_id=analysis_id, risk_code=alert["code"], actor="风险节点",
            )
            task_ids.append(task["task_id"])
        cases.record_analysis({
            "analysis_id": analysis_id, "session_id": session_id, "created_at": now(),
            "intent": metadata["intent"], "emotion": metadata["emotion"],
            "valence": metadata["valence"], "model_status": "chat_workflow",
            "usage": {"input_tokens": result["cost_info"].get("input_tokens", 0),
                      "output_tokens": result["cost_info"].get("output_tokens", 0)},
            "suggested_reply": result["response"], "task_ids": task_ids,
        })
        record_result(result, session_id)
        return jsonify(result), 200

    @app.get("/health")
    def health() -> tuple:
        """Report process health without claiming external integrations are healthy."""
        provider = os.getenv("QWEN_PROVIDER", "openai")
        base_url = os.getenv("QWEN_API_BASE", "http://127.0.0.1:11434/v1")
        key = os.getenv("QWEN_API_KEY", "")
        configured = is_loopback_url(base_url) if provider == "ollama" else bool(
            key and not key.startswith("your_"))
        return jsonify(status="ok", revision="workbench-v5",
                       assistance_revision=app.extensions["assist_agent"].prompt_version,
                       evaluation_revision="manual-evaluation-v2",
                       mode=os.getenv("EMBEDDING_BACKEND", "local"),
                       qwen_configured=configured, qwen_provider=provider,
                       qwen_models={"small": configured_model("small"),
                                    "large": configured_model("large")},
                       model_status="configured_not_probed" if configured else "not_configured"), 200

    @app.get("/")
    def index() -> object:
        return render_template("home.html")

    @app.get("/dashboard")
    def dashboard() -> str:
        """Render operational risk overview."""
        return render_template("dashboard_risk.html")

    @app.get("/workbench")
    def workbench() -> str:
        """Render the human-agent right-panel assistant workbench."""
        return render_template("workbench.html")

    @app.get("/evaluation")
    def evaluation_center() -> str:
        """Render the independent human evaluation workspace."""
        return render_template("evaluation_center.html")

    @app.get("/api/evaluation/annotations")
    def evaluation_annotations() -> tuple:
        split = request.args.get("split", "heldout")
        try:
            store = app.extensions["evaluation_store"]
            return jsonify(
                samples=store.list_samples(split),
                progress=store.annotation_progress(split),
                report=store.annotation_report(split),
                quality=store.quality_report(split),
            ), 200
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.get("/api/evaluation/annotations/<sample_id>")
    def evaluation_annotation(sample_id: str) -> tuple:
        try:
            return jsonify(app.extensions["evaluation_store"].get_sample(sample_id)), 200
        except KeyError:
            return jsonify(error="Sample not found"), 404

    @app.get("/api/evaluation/annotations/<sample_id>/suggestion")
    def evaluation_annotation_suggestion(sample_id: str) -> tuple:
        try:
            return jsonify(
                app.extensions["evaluation_store"].suggest_annotation(sample_id)
            ), 200
        except KeyError:
            return jsonify(error="Sample not found"), 404

    @app.post("/api/evaluation/annotations/<sample_id>")
    def save_evaluation_annotation(sample_id: str) -> tuple:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Expected JSON object"), 400
        try:
            annotation = app.extensions["evaluation_store"].save_annotation(sample_id, payload)
            return jsonify(annotation=annotation), 201
        except KeyError:
            return jsonify(error="Sample not found"), 404
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.get("/api/evaluation/efficiency/tasks")
    def evaluation_efficiency_tasks() -> tuple:
        store = app.extensions["evaluation_store"]
        return jsonify(tasks=store.list_efficiency_tasks(),
                       report=store.efficiency_report()), 200

    @app.get("/api/evaluation/efficiency/tasks/<task_id>/instructions")
    def evaluation_efficiency_instructions(task_id: str) -> tuple:
        method = request.args.get("method", "manual")
        try:
            return jsonify(
                app.extensions["efficiency_agent"].task_instructions(task_id, method)), 200
        except KeyError:
            return jsonify(error="Efficiency task not found"), 404

    @app.post("/api/evaluation/efficiency/trials")
    def start_efficiency_trial() -> tuple:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Expected JSON object"), 400
        try:
            trial = app.extensions["evaluation_store"].start_trial(
                str(payload.get("task_id", "")),
                str(payload.get("method", "")),
                str(payload.get("operator", "")),
            )
            return jsonify(trial=trial), 201
        except KeyError:
            return jsonify(error="Efficiency task not found"), 404
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.patch("/api/evaluation/efficiency/trials/<trial_id>")
    def stop_efficiency_trial(trial_id: str) -> tuple:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Expected JSON object"), 400
        try:
            trial = app.extensions["evaluation_store"].stop_trial(trial_id, payload)
            return jsonify(trial=trial), 200
        except KeyError:
            return jsonify(error="Trial not found"), 404
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.post("/api/evaluation/efficiency/trials/<trial_id>/invalidate")
    def invalidate_efficiency_trial(trial_id: str) -> tuple:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Expected JSON object"), 400
        actor, reason = payload.get("operator"), payload.get("reason")
        if not isinstance(actor, str) or not isinstance(reason, str):
            return jsonify(error="操作者和作废原因必须是文字"), 400
        try:
            trial = app.extensions["evaluation_store"].invalidate_trial(trial_id, actor, reason)
            return jsonify(trial=trial), 200
        except KeyError:
            return jsonify(error="Trial not found"), 404
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.get("/api/evaluation/efficiency/report")
    def efficiency_report() -> tuple:
        return jsonify(app.extensions["evaluation_store"].efficiency_report()), 200

    @app.get("/api/evaluation/efficiency/trials/<trial_id>")
    def efficiency_trial_detail(trial_id: str) -> tuple:
        try:
            return jsonify(app.extensions["evaluation_store"].trial_context(trial_id)), 200
        except KeyError:
            return jsonify(error="Trial not found"), 404

    @app.post("/api/evaluation/efficiency/trials/<trial_id>/assist")
    def efficiency_trial_assist(trial_id: str) -> tuple:
        try:
            detail = app.extensions["evaluation_store"].trial_context(trial_id)
        except KeyError:
            return jsonify(error="Trial not found"), 404
        if detail["trial"]["method"] != "copilot" or detail["trial"]["ended_at"]:
            return jsonify(error="Only an active copilot trial may request assistance"), 400
        sample = detail["sample"]
        context = _normalize_context(sample)
        key = SmartCache.key("study", trial_id, context)
        try:
            job = app.extensions["analysis_jobs"].submit(
                key, sample["sample_id"],
                lambda: app.extensions["assist_agent"].assist(
                    context, sample["buyer_message"], session_id=sample["sample_id"]),
            )
        except QueueFull:
            return jsonify(error="模型队列已满，请稍后重试"), 429
        return jsonify(job=job), 202

    @app.get("/api/sessions")
    def sessions() -> tuple:
        """List contest sessions for the demo selector."""
        store = app.extensions["contest_store"]
        return jsonify(sessions=store.list_sessions() if store else [],
                       source="contest_mock" if store else "empty"), 200

    @app.get("/api/sessions/<session_id>")
    def session_detail(session_id: str) -> tuple:
        """Return a cross-source context bundle for one session."""
        store = app.extensions["contest_store"]
        if not store:
            return jsonify(error="Contest data has not been imported"), 404
        before_message_id = request.args.get("before_message_id")
        mode = request.args.get("mode", "snapshot")
        try:
            detail = store.get_session(
                session_id, before_message_id=before_message_id, analysis_mode=mode,
            )
        except ValueError as error:
            return jsonify(error=str(error)), 400
        if not detail["messages"]:
            return jsonify(error="Session not found"), 404
        detail = store.with_service_history(
            detail, app.extensions["case_store"].consumer_identity(session_id),
        )
        return jsonify(detail), 200

    @app.post("/api/sessions/<session_id>/link")
    def confirm_identity(session_id: str) -> tuple:
        """Require a human identity decision before cross-session fusion."""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Expected JSON object"), 400
        peer = payload.get("other_session_id")
        actor, reason = payload.get("reviewer"), payload.get("reason")
        if not all(isinstance(value, str) for value in (peer, actor, reason)):
            return jsonify(error="Identity fields must be strings"), 400
        store = app.extensions["contest_store"]
        if not store or not store.get_session(session_id)["messages"] or not store.get_session(peer)["messages"]:
            return jsonify(error="Session not found"), 404
        try:
            identity = app.extensions["case_store"].link_sessions(session_id, peer, actor, reason)
        except ValueError as error:
            return jsonify(error=str(error)), 400
        socketio.emit("assist_update", {"session_id": session_id, "phase": "identity"})
        return jsonify(identity=identity), 201

    @app.post("/api/sessions/<session_id>/assist")
    def session_assist(session_id: str) -> tuple:
        """Generate a human-reviewable summary and reply draft."""
        store = app.extensions["contest_store"]
        if not store:
            return jsonify(error="Contest data has not been imported"), 404
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Expected JSON object"), 400
        message = payload.get("message", "")
        if not isinstance(message, str) or len(message) > 2000:
            return jsonify(error="message must be at most 2000 characters"), 400
        before_message_id = payload.get("before_message_id")
        mode = payload.get("mode", "snapshot")
        if mode not in ("snapshot", "replay") or (before_message_id is not None
                                               and not isinstance(before_message_id, str)):
            return jsonify(error="Invalid mode or analysis point"), 400
        try:
            result = app.extensions["workbench_workflow"].run(
                session_id, message.strip(), before_message_id, mode,
            )
        except KeyError:
            return jsonify(error="Session not found"), 404
        except ValueError as error:
            return jsonify(error=str(error)), 400
        return jsonify(result), 200

    @app.post("/api/sessions/<session_id>/assist-jobs")
    def queue_assistance(session_id: str) -> tuple:
        """Inspect risk immediately, then admit bounded background model work."""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Expected JSON object"), 400
        message, point, mode = payload.get("message", ""), payload.get("before_message_id"), payload.get("mode", "snapshot")
        if (not isinstance(message, str) or len(message) > 2000 or
                mode not in ("snapshot", "replay") or (point is not None and not isinstance(point, str))):
            return jsonify(error="Invalid message, analysis point or mode"), 400
        flow = app.extensions.get("workbench_workflow")
        if flow is None:
            return jsonify(error="Contest data has not been imported"), 404
        try:
            prepared = flow.prepare(session_id, message.strip(), point, mode)
            key = SmartCache.key(
                session_id, prepared["context"], prepared["message"], "assist-jobs-v1")
            job = app.extensions["analysis_jobs"].submit(
                key, session_id, lambda: flow.run_prepared(prepared),
            )
        except KeyError:
            return jsonify(error="Session not found"), 404
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except QueueFull as error:
            rejected = flow.record_rejection(prepared, "queue_full")
            return jsonify(
                error="分析队列已满，风险任务仍保留，请稍后重试",
                task_ids=prepared["task_ids"], analysis_id=rejected["analysis_id"],
            ), 429
        return jsonify(job=job, task_ids=prepared["task_ids"]), 202

    @app.get("/api/assist-jobs/<job_id>")
    def assistance_status(job_id: str) -> tuple:
        """Get background progress without rerunning inference."""
        try:
            job = app.extensions["analysis_jobs"].get(job_id)
        except KeyError:
            return jsonify(error="Job not found; the service may have restarted"), 404
        return jsonify(job=job), 200

    @app.get("/api/assist-jobs")
    def assistance_queue() -> tuple:
        return jsonify(app.extensions["analysis_jobs"].stats()), 200

    @app.get("/api/tasks")
    def tasks() -> tuple:
        """List human-review tasks."""
        session_id = request.args.get("session_id")
        status = request.args.get("status")
        try:
            tasks = app.extensions["case_store"].list_tasks(session_id, status)
        except ValueError as error:
            return jsonify(error=str(error)), 400
        return jsonify(tasks=tasks), 200

    @app.post("/api/tasks")
    def create_task() -> tuple:
        """Create a review task; this endpoint never executes business actions."""
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify(error="Expected JSON object"), 400
        if not isinstance(payload.get("session_id"), str) or not isinstance(payload.get("task_type"), str):
            return jsonify(error="session_id and task_type must be strings"), 400
        analysis_id = payload.get("analysis_id", "")
        try:
            if analysis_id:
                analysis = app.extensions["case_store"].get_analysis(analysis_id)
                if analysis["session_id"] != payload["session_id"]:
                    return jsonify(error="Analysis belongs to another session"), 400
            task = app.extensions["case_store"].create_task(
                str(payload.get("session_id", "")),
                str(payload.get("task_type", "")),
                str(payload.get("note", "")),
                priority=str(payload.get("priority", "medium")),
                owner=str(payload.get("owner", "")),
                analysis_id=str(payload.get("analysis_id", "")),
                risk_code=str(payload.get("risk_code", "")),
                actor=str(payload.get("actor", "客服")),
            )
        except KeyError:
            return jsonify(error="Analysis not found"), 404
        except ValueError as error:
            return jsonify(error=str(error)), 400
        socketio.emit("assist_update", {"session_id": task["session_id"], "phase": "task"})
        return jsonify(task=task), 201

    @app.patch("/api/tasks/<task_id>")
    def update_task(task_id: str) -> tuple:
        """Update only human task state, without touching the supplied business data."""
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify(error="Expected JSON object"), 400
        try:
            task = app.extensions["case_store"].update_task(
                task_id, str(payload.get("status", "")), str(payload.get("note", "")),
                owner=str(payload.get("owner", "")),
                actor=str(payload.get("actor", "客服")),
                due_at=payload.get("due_at"), waiting_on=payload.get("waiting_on"),
            )
        except KeyError:
            return jsonify(error="Task not found"), 404
        except ValueError as error:
            return jsonify(error=str(error)), 400
        socketio.emit("assist_update", {"session_id": task["session_id"], "phase": "task"})
        return jsonify(task=task), 200

    @app.post("/api/analyses/<analysis_id>/review")
    def review_analysis(analysis_id: str) -> tuple:
        """Record a human decision without sending anything to the buyer."""
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify(error="Expected JSON object"), 400
        try:
            feedback = app.extensions["case_store"].review(
                analysis_id,
                str(payload.get("decision", "")),
                str(payload.get("edited_reply", "")),
                str(payload.get("reason", "")),
                str(payload.get("reviewer", "客服")),
            )
        except KeyError:
            return jsonify(error="Analysis not found"), 404
        except ValueError as error:
            return jsonify(error=str(error)), 400
        return jsonify(feedback=feedback), 201

    @app.get("/api/sessions/<session_id>/analyses")
    def session_analyses(session_id: str) -> tuple:
        """Return analysis and review records for audit."""
        analyses = app.extensions["case_store"].recent_analyses(session_id)
        return jsonify(analyses=analyses,
                       feedback=app.extensions["case_store"].feedback(session_id)), 200

    @app.get("/api/feedback/summary")
    def feedback_summary() -> tuple:
        return jsonify(app.extensions["case_store"].feedback_summary()), 200

    @app.get("/api/dashboard")
    def dashboard_data() -> tuple:
        """Return persistent, distinct-session operational metrics."""
        return jsonify(app.extensions["case_store"].dashboard()), 200

    @app.get("/api/cost")
    def cost_data() -> tuple:
        """Return measured cost and cache statistics."""
        persistent = app.extensions["case_store"].usage_stats()
        response_agent = app.extensions["workflow"].response_agent
        legacy = response_agent.tracker.get_stats()
        if legacy["total_tokens"]:
            persistent["cost"]["workflow_tokens"] = legacy["total_tokens"]
        return jsonify(**persistent), 200

    @app.get("/api/performance")
    def performance_data() -> tuple:
        return jsonify(
            performance=app.extensions["case_store"].performance_stats(),
            queue=app.extensions["analysis_jobs"].stats(),
        ), 200

    @app.errorhandler(Exception)
    def handle_error(error: Exception) -> tuple:
        """Do not expose internals in unexpected error responses."""
        if isinstance(error, HTTPException):
            return jsonify(error=error.description), error.code
        logger.exception("Unhandled API failure")
        return jsonify(error="Internal server error"), 500

    return app


if __name__ == "__main__":
    from src.api.websocket_handler import socketio

    socketio.run(create_app(), host="127.0.0.1", port=5000, debug=False,
                 allow_unsafe_werkzeug=True)
