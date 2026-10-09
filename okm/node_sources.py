"""Map logical map nodes → real source files in the ingested repo.

Local + auditable. MCP remoto = fase 2 cuando el expediente no alcanza.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Any

from okm.store import ExpedienteStore

# focus id / role label → paths relative to source root (primero = primario)
NODE_SOURCE_MAP: dict[str, list[str]] = {
    "role:ingest": ["okm/ingest.py", "okm/pipeline.py", "okm/extract.py", "okm/cli.py"],
    "ingest": ["okm/ingest.py", "okm/pipeline.py", "okm/extract.py"],
    "role:expediente": ["okm/store.py", "okm/models.py"],
    "expediente": ["okm/store.py", "okm/models.py"],
    "role:combinado": ["okm/noc_combined.py", "okm/engines.py"],
    "combinado": ["okm/noc_combined.py", "okm/engines.py"],
    "role:archify": ["okm/archify_adapter.py", "okm/archify_graph.py"],
    "archify": ["okm/archify_adapter.py", "okm/archify_graph.py"],
    "role:openapi": ["okm/openapi_graph.py"],
    "openapi": ["okm/openapi_graph.py"],
    "role:asistente": ["okm/agent.py", "okm/ask.py", "okm/audit.py"],
    "asistente": ["okm/agent.py", "okm/ask.py"],
    "role:serve": ["okm/serve.py", "okm/static/index.html"],
    "briefing": ["okm/serve.py", "okm/static/index.html"],
    "serve": ["okm/serve.py", "okm/static/index.html"],
}

_FOCUS_LABELS: dict[str, str] = {
    "role:ingest": "Ingest",
    "ingest": "Ingest",
    "role:expediente": "Expediente",
    "expediente": "Expediente",
    "role:combinado": "Combinado",
    "combinado": "Combinado",
    "role:archify": "Archify",
    "archify": "Archify",
    "role:openapi": "OpenAPI",
    "openapi": "OpenAPI",
    "role:asistente": "Asistente",
    "asistente": "Asistente",
    "role:serve": "Briefing",
    "briefing": "Briefing",
    "serve": "Briefing",
}

_CODE_ASK = re.compile(
    r"\b(c[oó]digo|source|fuente|implementaci[oó]n|archivo|\.py\b|mostrame|dame|analiz)\b",
    re.IGNORECASE,
)

# Cap solo para dossier LLM — export siempre completo.
_MAX_CHARS_DOSSIER = 14_000
_MAX_FILES = 4


def human_focus_label(focus_node: str | None) -> str:
    if not focus_node:
        return "nodo"
    key = focus_node.strip().lower()
    if key in _FOCUS_LABELS:
        return _FOCUS_LABELS[key]
    if ":" in key:
        tail = key.split(":")[-1]
        if tail in _FOCUS_LABELS:
            return _FOCUS_LABELS[tail]
        return tail.capitalize()
    return focus_node.strip()


def resolve_source_root(store: ExpedienteStore) -> Path | None:
    run = store.latest_run() or {}
    uri = str(run.get("source_uri") or "").strip()
    if uri:
        p = Path(uri)
        if p.is_dir():
            return p.resolve()
        cache = store.workspace / "source_cache"
        if cache.is_dir():
            kids = [c for c in cache.iterdir() if c.is_dir()]
            if len(kids) == 1:
                return kids[0].resolve()
    parent = store.workspace.parent
    if (parent / "okm").is_dir():
        return parent.resolve()
    return None


def paths_for_focus(
    focus_node: str | None, question: str = "", *, max_files: int | None = None
) -> list[str]:
    keys: list[str] = []
    if focus_node:
        raw = focus_node.strip()
        keys.append(raw.lower())
        if ":" in raw:
            keys.append(raw.split(":")[-1].lower())
        keys.append(raw.lower().replace("role:", ""))
    q = question.lower()
    for key in NODE_SOURCE_MAP:
        if len(key) >= 4 and key in q:
            keys.append(key)
    seen: list[str] = []
    out: list[str] = []
    for k in keys:
        for rel in NODE_SOURCE_MAP.get(k, []):
            if rel not in seen:
                seen.append(rel)
                out.append(rel)
    limit = _MAX_FILES if max_files is None else max(1, max_files)
    return out[:limit]


def wants_source_code(question: str) -> bool:
    return bool(_CODE_ASK.search(question or ""))


def _safe_file(root: Path, rel: str) -> Path | None:
    path = (root / rel).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    return path if path.is_file() else None


def read_node_sources(
    store: ExpedienteStore,
    *,
    focus_node: str | None,
    question: str = "",
    for_dossier: bool = True,
    depth: str = "quick",
) -> list[dict[str, Any]]:
    """Return source file dicts. for_dossier=True truncates content for LLM."""
    deep = (depth or "quick").lower() == "deep"
    max_files = 8 if deep else _MAX_FILES
    max_chars = 28_000 if deep else _MAX_CHARS_DOSSIER
    rels = paths_for_focus(focus_node, question, max_files=max_files)
    if not rels:
        return []
    root = resolve_source_root(store)
    if root is None:
        return []
    opened: list[dict[str, Any]] = []
    for i, rel in enumerate(rels):
        path = _safe_file(root, rel)
        if path is None:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        truncated = for_dossier and len(text) > max_chars
        content = text[:max_chars] if truncated else text
        opened.append(
            {
                "path": rel.replace("\\", "/"),
                "abs": str(path),
                "chars": len(text),
                "content": content,
                "truncated": truncated,
                "role": "primary" if i == 0 else "anexo",
            }
        )
    return opened


def format_sources_block(files: list[dict[str, Any]]) -> str:
    if not files:
        return ""
    lines = ["CÓDIGO FUENTE DEL NODO (archivos reales del repo):"]
    for f in files:
        note = " (truncado para el dossier)" if f.get("truncated") else ""
        lines.append(f"\n--- {f['path']} · {f['chars']} chars · {f.get('role', '')}{note} ---")
        lines.append(f["content"])
    return "\n".join(lines)


def export_payload(files: list[dict[str, Any]], focus_node: str | None) -> dict[str, Any]:
    label = human_focus_label(focus_node)
    primary = files[0]["path"] if files else None
    return {
        "label": label,
        "focus_node": focus_node,
        "primary": primary,
        "files": [
            {
                "path": f["path"],
                "chars": f["chars"],
                "role": f.get("role") or ("primary" if i == 0 else "anexo"),
                "url": f"/api/source/file?focus={_q(focus_node)}&path={_q(f['path'])}",
            }
            for i, f in enumerate(files)
        ],
        "bundle_url": (
            f"/api/source/bundle?focus={_q(focus_node)}" if files else None
        ),
    }


def _q(value: str | None) -> str:
    from urllib.parse import quote

    return quote(value or "", safe="")


def short_code_answer(files: list[dict[str, Any]], focus_node: str | None) -> str:
    """Chat-friendly answer: no wall of code — UI ofrece Copiar/Descargar."""
    label = human_focus_label(focus_node)
    if not files:
        return (
            f"**Qué es**\nPediste código de «{label}», pero no hay archivos mapeados "
            "o no encontré el root del source.\n\n"
            "**Huecos**\nSin fuente local. Más adelante MCP remoto puede traerla.\n"
        )
    primary = next((f for f in files if f.get("role") == "primary"), files[0])
    anexos = [f for f in files if f is not primary]
    lines = [
        f"**Qué es**\nCódigo real del nodo **{label}** (repo local, auditable).",
        "",
        f"**Primario**\n`{primary['path']}` · {primary['chars']} caracteres",
    ]
    if anexos:
        lines.append("")
        lines.append("**También usa**")
        for f in anexos:
            lines.append(f"- `{f['path']}` · {f['chars']} caracteres")
    lines.extend(
        [
            "",
            "**Cómo llevártelo**\n"
            "Usá **Copiar** o **Descargar** abajo (archivo completo, sin truncar). "
            "No lo pegamos entero en el chat.",
            "",
            "**Siguiente**\nLa consulta quedó en `audit/ask/` del workspace.",
        ]
    )
    return "\n".join(lines)


# Back-compat name used by agent
def deterministic_code_answer(
    files: list[dict[str, Any]], focus_node: str | None
) -> str:
    return short_code_answer(files, focus_node)


def _path_allowed_for_focus(
    store: ExpedienteStore, focus_node: str | None, rel: str
) -> bool:
    """Allow mapped node files, evidence paths, or files under a service root."""
    if rel in set(paths_for_focus(focus_node, "")):
        return True
    for ev in store.list_evidence():
        if (ev.path or "").replace("\\", "/") == rel:
            return True
    if not focus_node:
        return False
    raw = focus_node.strip()
    sid = raw[4:] if raw.startswith("svc:") else raw
    for s in store.list_services():
        match = (
            s.service_id == sid
            or s.name == sid
            or f"svc:{s.service_id}" == raw
            or s.name.lower() == sid.lower()
        )
        if not match:
            continue
        prefix = (s.root_path or s.name or "").replace("\\", "/").strip("/")
        if prefix and (rel == prefix or rel.startswith(prefix + "/")):
            return True
    return False


def read_single_source(
    store: ExpedienteStore, *, focus_node: str | None, rel_path: str
) -> dict[str, Any] | None:
    root = resolve_source_root(store)
    if root is None:
        return None
    rel = rel_path.replace("\\", "/").lstrip("/")
    if not _path_allowed_for_focus(store, focus_node, rel):
        return None
    path = _safe_file(root, rel)
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return {"path": rel, "chars": len(text), "content": text, "abs": str(path)}


def build_source_zip(
    store: ExpedienteStore, *, focus_node: str | None, question: str = ""
) -> tuple[bytes, str] | None:
    files = read_node_sources(
        store, focus_node=focus_node, question=question, for_dossier=False
    )
    if not files:
        return None
    label = human_focus_label(focus_node).lower().replace(" ", "-")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        readme = [
            f"Noc152 export · {human_focus_label(focus_node)}",
            "Archivos completos del nodo (repo local).",
            "",
        ]
        for f in files:
            readme.append(f"- {f['path']} ({f['chars']} chars) [{f.get('role')}]")
            zf.writestr(f["path"], f["content"])
        zf.writestr("README.txt", "\n".join(readme) + "\n")
    return buf.getvalue(), f"noc152-{label}-sources.zip"
