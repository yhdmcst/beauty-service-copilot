"""Realtime alert feed with bounded in-process dashboard statistics."""

from __future__ import annotations

import threading
import hashlib
from collections import Counter, deque
from datetime import datetime, timezone

from flask_socketio import SocketIO

socketio = SocketIO(cors_allowed_origins=None, async_mode="threading")
_lock = threading.RLock()
_alerts: deque[dict] = deque(maxlen=100)
_events: deque[dict] = deque(maxlen=500)
_stats: Counter = Counter()


def init_socketio(app: object) -> SocketIO:
    """Attach Socket.IO to Flask without wildcard CORS."""
    socketio.init_app(app)
    return socketio


@socketio.on("subscribe_alerts")
def subscribe_alerts() -> dict:
    """Confirm subscription; clients receive same-origin broadcasts."""
    return {"subscribed": True}


def record_result(result: dict, session_id: str) -> None:
    """Store aggregate dashboard event and emit actionable alerts immediately."""
    metadata = result["metadata"]
    event = {"time": datetime.now(timezone.utc).isoformat(), "emotion": metadata["emotion"],
             "valence": metadata["valence"],
             "intent": metadata["intent"], "risk_level": metadata["risk_level"]}
    safe_session = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:8]
    with _lock:
        _events.append(event)
        _stats["served"] += 1
        _stats["risk"] += metadata["risk_level"] in ("critical", "high")
        for rule in metadata.get("alerts", []):
            alert = {"session_id": safe_session, "time": event["time"], "name": rule["name"],
                     "level": rule["level"], "action": rule["action"],
                     "risk_score": metadata["risk_score"], "intent": metadata["intent"]}
            _alerts.appendleft(alert)
            socketio.emit("new_alert", alert)


def dashboard_snapshot() -> dict:
    """Expose only non-PII metrics and recent alert metadata."""
    with _lock:
        events = list(_events)
        return {
            "served": _stats["served"], "high_risk": _stats["risk"],
            "satisfaction": None, "alerts": list(_alerts)[:30],
            "emotion_trend": [{"time": item["time"], "emotion": item["emotion"],
                               "valence": item["valence"]}
                              for item in events[-40:]],
            "intent_distribution": dict(Counter(item["intent"] for item in events)),
        }
