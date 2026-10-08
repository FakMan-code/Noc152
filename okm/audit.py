"""Audit trail for ask/agent (and future MCP) — JSONL under workspace/audit/."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def audit_dir(workspace: Path) -> Path:
    return workspace / "audit" / "ask"


def write_ask_audit(
    workspace: Path,
    *,
    question: str,
    service: str | None,
    focus_node: str | None,
    mode: str,
    model: str | None,
    answer: str,
    ok: bool,
    sources_opened: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Append one ask event. Returns the log file path."""
    root = audit_dir(workspace)
    root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y%m%d")
    path = root / f"{day}.jsonl"
    event = {
        "id": str(uuid.uuid4()),
        "ts": now.isoformat(),
        "channel": "ask",
        "ok": ok,
        "question": question,
        "service": service,
        "focus_node": focus_node,
        "mode": mode,
        "model": model,
        "sources_opened": sources_opened or [],
        "auth": {
            "kind": "local",
            "note": "sin auth remota; workspace local",
        },
        "answer_chars": len(answer or ""),
        "answer_preview": (answer or "")[:800],
    }
    if extra:
        event["extra"] = extra
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return path
