"""SQLite-backed assistance, human review and risk-task audit records."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

TRANSITIONS = {
    "pending": {"in_progress", "cancelled"},
    "in_progress": {"resolved", "cancelled"},
    "resolved": set(),
    "cancelled": set(),
}


def now() -> str:
    """Return a timezone-aware audit timestamp."""
    return datetime.now(timezone.utc).isoformat()


class CaseStore:
    """Persist demo records; use :memory: explicitly for isolated tests."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=5)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                task_type TEXT NOT NULL, note TEXT NOT NULL, status TEXT NOT NULL,
                owner TEXT NOT NULL, priority TEXT NOT NULL, risk_code TEXT NOT NULL,
                analysis_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS tasks_session ON tasks(session_id, status);
            CREATE TABLE IF NOT EXISTS task_history (
                event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, action TEXT NOT NULL,
                actor TEXT NOT NULL, note TEXT NOT NULL, time TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS analyses (
                analysis_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                created_at TEXT NOT NULL, data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS analyses_session ON analyses(session_id, created_at);
            CREATE TABLE IF NOT EXISTS feedback (
                analysis_id TEXT PRIMARY KEY, decision TEXT NOT NULL,
                edited_reply TEXT NOT NULL, reason TEXT NOT NULL,
                reviewer TEXT NOT NULL, time TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS consumer_links (
                session_id TEXT PRIMARY KEY, consumer_id TEXT NOT NULL,
                reviewer TEXT NOT NULL, reason TEXT NOT NULL, confirmed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS consumer_group ON consumer_links(consumer_id);
        """)
        self._db.commit()

    def _audit(self, task_id: str, action: str, actor: str, note: str) -> None:
        self._db.execute(
            "INSERT INTO task_history VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), task_id, action, actor, note, now()),
        )

    def create_task(
        self, session_id: str, task_type: str, note: str = "", *,
        priority: str = "medium", owner: str = "", analysis_id: str = "",
        risk_code: str = "", actor: str = "客服",
    ) -> dict:
        """Deduplicate active tasks for the same session and risk/action."""
        if not session_id.strip() or not task_type.strip():
            raise ValueError("session_id and task_type are required")
        if priority not in {"low", "medium", "high", "critical"}:
            raise ValueError("invalid priority")
        with self._lock, self._db:
            existing = self._db.execute(
                """SELECT * FROM tasks WHERE session_id=? AND
                (risk_code=? AND ?<>'' OR task_type=? AND ?='')
                AND status IN ('pending', 'in_progress') LIMIT 1""",
                (session_id, risk_code, risk_code, task_type, risk_code),
            ).fetchone()
            if existing:
                return self._task(dict(existing))
            task_id, timestamp = str(uuid.uuid4()), now()
            self._db.execute(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, session_id, task_type[:80], note[:500], "pending",
                 owner[:40], priority, risk_code, analysis_id, timestamp, timestamp),
            )
            self._audit(task_id, "created", actor[:40], note[:500])
            return self.get_task(task_id)

    def _task(self, row: dict) -> dict:
        row["history"] = [dict(event) for event in self._db.execute(
            "SELECT action, actor, note, time FROM task_history WHERE task_id=? ORDER BY time",
            (row["task_id"],),
        )]
        return row

    def get_task(self, task_id: str) -> dict:
        """Retrieve a task and its operation history."""
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,),
            ).fetchone()
            if not row:
                raise KeyError(task_id)
            return self._task(dict(row))

    def update_task(
        self, task_id: str, status: str, note: str = "", *, owner: str = "",
        actor: str = "客服",
    ) -> dict:
        """Enforce lifecycle; closing requires a disposition note."""
        with self._lock, self._db:
            task = self.get_task(task_id)
            if status not in TRANSITIONS[task["status"]]:
                raise ValueError("Task transition is not allowed")
            if status in {"resolved", "cancelled"} and not note.strip():
                raise ValueError("A disposition note is required")
            assigned = owner.strip() or task["owner"] or actor.strip()
            if status == "in_progress" and not assigned:
                raise ValueError("An owner is required")
            self._db.execute(
                "UPDATE tasks SET status=?, note=?, owner=?, updated_at=? WHERE task_id=?",
                (status, note[:500] or task["note"], assigned[:40], now(), task_id),
            )
            self._audit(task_id, status, actor[:40], note[:500])
            return self.get_task(task_id)

    def list_tasks(self, session_id: str | None = None, status: str | None = None) -> list[dict]:
        """Return active and closed tasks, optionally filtered."""
        clauses, params = [], []
        if session_id:
            clauses.append("session_id=?")
            params.append(session_id)
        if status:
            if status not in TRANSITIONS:
                raise ValueError("invalid status")
            clauses.append("status=?")
            params.append(status)
        query = "SELECT * FROM tasks"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        with self._lock:
            return [self._task(dict(row)) for row in self._db.execute(
                """{} ORDER BY
                CASE priority
                    WHEN 'critical' THEN 0
                    WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2
                    ELSE 3
                END,
                CASE status
                    WHEN 'pending' THEN 0
                    WHEN 'in_progress' THEN 1
                    WHEN 'resolved' THEN 2
                    ELSE 3
                END,
                updated_at DESC""".format(query), params,
            )]

    def record_analysis(self, result: dict) -> None:
        """Store measured usage and validated assistance, not private raw prompts."""
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO analyses VALUES (?, ?, ?, ?)",
                (result["analysis_id"], result["session_id"], now(),
                 json.dumps(result, ensure_ascii=False)),
            )

    def get_analysis(self, analysis_id: str) -> dict:
        """Look up exactly the analysis being reviewed."""
        with self._lock:
            row = self._db.execute(
                "SELECT data FROM analyses WHERE analysis_id=?", (analysis_id,),
            ).fetchone()
            if not row:
                raise KeyError(analysis_id)
            return json.loads(row["data"])

    def recent_analyses(self, session_id: str | None = None, limit: int = 100) -> list[dict]:
        """Read the most recent analysis records."""
        with self._lock:
            if session_id:
                rows = self._db.execute(
                    "SELECT data FROM analyses WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
                    (session_id, limit),
                )
            else:
                rows = self._db.execute(
                    "SELECT data FROM analyses ORDER BY created_at DESC LIMIT ?", (limit,),
                )
            return [json.loads(row["data"]) for row in rows]

    def review(
        self, analysis_id: str, decision: str, edited_reply: str, reason: str,
        reviewer: str,
    ) -> dict:
        """Record human approval only; no customer message is sent."""
        if decision not in {"accepted", "edited", "rejected"}:
            raise ValueError("invalid review decision")
        if not reviewer.strip():
            raise ValueError("Reviewer is required")
        analysis = self.get_analysis(analysis_id)
        if decision != "rejected" and not edited_reply.strip():
            raise ValueError("Reply is required")
        if decision == "rejected" and not reason.strip():
            raise ValueError("A rejection reason is required")
        if decision == "accepted" and edited_reply.strip() != analysis["suggested_reply"].strip():
            raise ValueError("Changed replies must be recorded as edited")
        record = {
            "analysis_id": analysis_id, "decision": decision,
            "edited_reply": edited_reply[:1000], "reason": reason[:500],
            "reviewer": reviewer[:40], "time": now(),
        }
        with self._lock, self._db:
            if self._db.execute(
                "SELECT 1 FROM feedback WHERE analysis_id=?", (analysis_id,),
            ).fetchone():
                raise ValueError("This analysis has already been reviewed")
            self._db.execute("INSERT INTO feedback VALUES (?, ?, ?, ?, ?, ?)", tuple(record.values()))
        return record

    def feedback(self, session_id: str) -> list[dict]:
        """Return reviewer decisions for a customer session."""
        with self._lock:
            return [dict(row) for row in self._db.execute(
                """SELECT f.* FROM feedback f JOIN analyses a
                ON a.analysis_id=f.analysis_id WHERE a.session_id=? ORDER BY f.time DESC""",
                (session_id,),
            )]

    def link_sessions(self, session_id: str, other_session_id: str, reviewer: str, reason: str) -> dict:
        """Save an explicit human identity decision; never match masked nicknames."""
        if session_id == other_session_id or not session_id or not other_session_id:
            raise ValueError("Two different sessions are required")
        if not reviewer.strip() or not reason.strip():
            raise ValueError("Reviewer and identity-confirmation reason are required")
        if len(reviewer) > 40 or len(reason) > 500:
            raise ValueError("Identity-confirmation fields are too long")
        with self._lock, self._db:
            rows = self._db.execute(
                "SELECT * FROM consumer_links WHERE session_id IN (?, ?)",
                (session_id, other_session_id),
            ).fetchall()
            groups = {row["consumer_id"] for row in rows}
            if len(groups) > 1:
                raise ValueError("Conflicting confirmed groups require separate reconciliation")
            group = next(iter(groups), str(uuid.uuid4()))
            for linked_id in (session_id, other_session_id):
                self._db.execute(
                    "INSERT OR IGNORE INTO consumer_links VALUES (?, ?, ?, ?, ?)",
                    (linked_id, group, reviewer, reason, now()),
                )
            return self.consumer_identity(session_id)

    def consumer_identity(self, session_id: str) -> dict:
        """Expose confirmed session membership and audit reasons, not a claimed platform ID."""
        with self._lock:
            row = self._db.execute(
                "SELECT consumer_id FROM consumer_links WHERE session_id=?", (session_id,),
            ).fetchone()
            if not row:
                return {"basis": "unconfirmed", "sessions": [session_id], "confirmations": []}
            members = [dict(item) for item in self._db.execute(
                """SELECT session_id, reviewer, reason, confirmed_at FROM consumer_links
                WHERE consumer_id=? ORDER BY confirmed_at, session_id""", (row["consumer_id"],),
            )]
            return {
                "basis": "human_confirmed_demo_identity",
                "sessions": [item["session_id"] for item in members], "confirmations": members,
            }

    def dashboard(self) -> dict:
        """Use distinct sessions for counts; task states determine open risk."""
        with self._lock:
            sessions = self._db.execute(
                "SELECT COUNT(DISTINCT session_id) FROM analyses",
            ).fetchone()[0]
            analysis_count = self._db.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
            reviewed = self._db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
            accepted = self._db.execute(
                "SELECT COUNT(*) FROM feedback WHERE decision IN ('accepted', 'edited')",
            ).fetchone()[0]
        tasks = self.list_tasks()
        alerts = [{
            **task, "name": task["task_type"], "level": task["priority"],
            "action": task["note"], "time": task["updated_at"],
            "risk_score": {"critical": 90, "high": 70, "medium": 50, "low": 0}[task["priority"]],
        } for task in tasks if task["risk_code"]]
        events = self.recent_analyses(limit=100)
        distribution: dict[str, int] = {}
        for event in events:
            intent = event.get("intent", "待核实")
            distribution[intent] = distribution.get(intent, 0) + 1
        return {
            "served": sessions, "analysis_count": analysis_count,
            "high_risk": len({task["session_id"] for task in tasks if
                              task["status"] in {"pending", "in_progress"} and
                              task["priority"] in {"high", "critical"}}),
            "open_tasks": sum(task["status"] in {"pending", "in_progress"} for task in tasks),
            "closed_tasks": sum(task["status"] == "resolved" for task in tasks),
            "satisfaction": None,
            "adoption_rate": accepted / reviewed if reviewed else None,
            "reviewed_count": reviewed, "alerts": alerts[:100],
            "emotion_trend": [{"time": event.get("created_at"), "emotion": event.get("emotion"),
                               "valence": event.get("valence", 0)}
                              for event in reversed(events[:40])],
            "intent_distribution": distribution,
        }

    def usage_stats(self) -> dict:
        """Return actual tokens; currency requires separate configured pricing."""
        with self._lock:
            records = [json.loads(row[0]) for row in self._db.execute("SELECT data FROM analyses")]
        distribution: dict[str, int] = {}
        tokens, hits, input_tokens, output_tokens = 0, 0, 0, 0
        for record in records:
            usage = record.get("usage", {})
            tokens += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            input_tokens += usage.get("input_tokens", 0)
            output_tokens += usage.get("output_tokens", 0)
            hits += bool(record.get("cache_hit"))
            model = "cache" if record.get("cache_hit") else (
                record.get("model") or record.get("model_status", "rule"))
            distribution[model] = distribution.get(model, 0) + 1
        return {
            "cost": {"total_tokens": tokens, "total_cost_cny": None,
                     "input_tokens": input_tokens, "output_tokens": output_tokens,
                     "pricing_configured": False, "model_distribution": distribution,
                     "sessions": len({record["session_id"] for record in records}),
                     "billing_scope": "Token usage only; hardware/cloud charges not evaluated"},
            "cache": {"hits": hits, "misses": len(records) - hits,
                      "hit_rate": hits / len(records) if records else 0},
        }

    def performance_stats(self) -> dict:
        """Exclude cached and rule-only analysis from model-generation latency."""
        records = self.recent_analyses(limit=1000)
        live = [row for row in records if not row.get("cache_hit")
                and row.get("usage", {}).get("output_tokens", 0) > 0
                and isinstance(row.get("latency_ms"), (int, float))]
        latencies = sorted(row["latency_ms"] for row in live)
        return {
            "scope": "recent 1000 recorded analyses; generation excludes cache/rule-only",
            "generation_n": len(latencies),
            "p50_ms": statistics.median(latencies) if latencies else None,
            "p95_ms": latencies[max(0, math.ceil(len(latencies) * .95) - 1)] if latencies else None,
            "cached_n": sum(bool(row.get("cache_hit")) for row in records),
            "fallback_n": sum(row.get("model_status") == "fallback" for row in records),
            "pricing_scope": "local hardware/electricity not measured",
        }

    def close(self) -> None:
        """Release database resources."""
        with self._lock:
            self._db.close()
