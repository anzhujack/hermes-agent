"""Privacy-preserving execution audit for delegated subagents.

The lifecycle hooks intentionally ignore child goals and summaries.  They retain
only bounded status metadata and opaque references needed to correlate starts
with stops.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from datetime import datetime, timezone
from typing import Any

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)
_AUDIT_LOCK = threading.Lock()
_ROLE_VALUES = {
    "leaf",
    "orchestrator",
    "coordinator",
    "researcher",
    "writer",
    "builder",
}
_STATUS_ALIASES = {
    "success": "completed",
    "complete": "completed",
    "ok": "completed",
    "failed": "failed",
    "error": "failed",
    "timed_out": "timed_out",
    "timeout": "timed_out",
    "interrupted": "interrupted",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}
_MAX_DURATION_MS = 7 * 24 * 60 * 60 * 1000


def _audit_path():
    return get_hermes_home() / "wiki" / "logs" / "delegation_executions.jsonl"


def _opaque_ref(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return hashlib.sha256(f"lchd-personal-v1:{text}".encode("utf-8")).hexdigest()[:16]


def _safe_role(value: Any) -> str:
    role = re.sub(r"[^a-z0-9_-]", "", str(value or "").strip().lower())[:32]
    return role if role in _ROLE_VALUES else "unknown"


def _safe_status(value: Any) -> str:
    status = re.sub(r"[^a-z0-9_-]", "_", str(value or "").strip().lower())[:32]
    return _STATUS_ALIASES.get(
        status, status if status in set(_STATUS_ALIASES.values()) else "unknown"
    )


def _safe_duration_ms(value: Any) -> int:
    try:
        duration = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(duration, _MAX_DURATION_MS))


def _append_lifecycle(event: str, **kwargs: Any) -> None:
    child_ref_source = kwargs.get("child_session_id") or kwargs.get("child_subagent_id")
    record: dict[str, Any] = {
        "schema_version": 1,
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "parent_session_ref": _opaque_ref(kwargs.get("parent_session_id")),
        "parent_turn_ref": _opaque_ref(kwargs.get("parent_turn_id")),
        "child_session_ref": _opaque_ref(child_ref_source),
        "child_role": _safe_role(kwargs.get("child_role")),
    }
    if event == "subagent_stop":
        record["status"] = _safe_status(kwargs.get("child_status"))
        record["duration_ms"] = _safe_duration_ms(kwargs.get("duration_ms"))

    path = _audit_path()
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    with _AUDIT_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()


def on_subagent_start(**kwargs: Any) -> None:
    try:
        _append_lifecycle("subagent_start", **kwargs)
    except Exception:
        logger.debug("Lchd subagent_start audit failed", exc_info=True)


def on_subagent_stop(**kwargs: Any) -> None:
    try:
        _append_lifecycle("subagent_stop", **kwargs)
    except Exception:
        logger.debug("Lchd subagent_stop audit failed", exc_info=True)
