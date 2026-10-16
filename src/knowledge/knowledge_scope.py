"""Metadata eligibility independent of retrieval similarity or ranking."""

from datetime import date


def eligible_document(doc: dict, intent: str, context: dict | None = None) -> bool:
    context = context or {}
    allowed = doc.get("applicable_intents")
    if allowed is not None and (not isinstance(allowed, list) or intent not in allowed):
        return False
    for key in ("brand", "product_id", "channel", "service_focus"):
        required = doc.get(key)
        if required and required != "*" and context.get(key) != required:
            return False
    for key in ("effective_from", "effective_to"):
        if doc.get(key):
            try:
                at = date.fromisoformat(str(context.get("analysis_at", ""))[:10])
                boundary = date.fromisoformat(doc[key])
            except (ValueError, TypeError):
                return False
            if key == "effective_from" and at < boundary or key == "effective_to" and at > boundary:
                return False
    return doc.get("review_status") not in {"retired", "rejected"}
