"""Discover independent ingested roots (demo workspaces) — one repo per root."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from okm.humanize import is_noise_service, source_display_name
from okm.noc_combined import is_self_map_workspace, self_map_part_count
from okm.store import ExpedienteStore

_FOLDER_LABELS: dict[str, str] = {
    "demo_martian": "Martian Bank",
    "demo_noc152": "Noc152 (este proyecto)",
    "demo_boutique": "Online Boutique",
    "demo_httpx": "httpx",
    "okm_workspace": "Workspace local",
}


def _label_for(folder: str, source_uri: str | None) -> str:
    key = folder.lstrip(".").lower()
    if key in _FOLDER_LABELS:
        return _FOLDER_LABELS[key]
    uri = (source_uri or "").lower()
    if "martian-bank" in uri:
        return "Martian Bank"
    if "microservices-demo" in uri:
        return "Online Boutique"
    if "proyecto-noc-152" in uri.replace("\\", "/"):
        return "Noc152 (este proyecto)"
    if "httpx" in uri:
        return "httpx"
    title = source_display_name(source_uri)
    if title and title.lower() not in {"noc152"}:
        return title
    return folder.lstrip(".")


def discover_roots(anchor: Path) -> list[dict[str, Any]]:
    """Find sibling `.demo_*` / `.okm_workspace` directories with an expediente.

    Each root is an independent repo ingest — they do not share a graph.
    """
    anchor = anchor.expanduser().resolve()
    if anchor.name.startswith(".demo") or anchor.name == ".okm_workspace":
        base = anchor.parent
    else:
        base = anchor

    candidates: list[Path] = []
    seen: set[Path] = set()
    if base.is_dir():
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            name = child.name
            if not (name.startswith(".demo") or name == ".okm_workspace"):
                continue
            if not (child / "expediente.sqlite3").is_file():
                continue
            resolved = child.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            candidates.append(resolved)

    roots: list[dict[str, Any]] = []
    for path in candidates:
        rid = path.name.lstrip(".")
        source_uri = None
        n_svc = 0
        try:
            store = ExpedienteStore(path)
            try:
                run = store.latest_run() or {}
                source_uri = run.get("source_uri")
                visible = [
                    s for s in store.list_services() if not is_noise_service(s.name)
                ]
                n_svc = len(visible)
                label = _label_for(path.name, source_uri)
                if n_svc == 0 and is_self_map_workspace(
                    source_uri, label, visible, workspace=path
                ):
                    n_svc = self_map_part_count()  # capas lógicas, no microservicios
            finally:
                store.close()
        except OSError:
            continue
        roots.append(
            {
                "id": rid,
                "label": _label_for(path.name, source_uri),
                "path": str(path),
                "source_uri": source_uri,
                "services": n_svc,
            }
        )

    order = {
        "demo_martian": 0,
        "demo_noc152": 1,
        "demo_boutique": 2,
        "demo_httpx": 3,
        "okm_workspace": 4,
    }
    roots.sort(key=lambda r: (order.get(r["id"], 9), r["label"].lower()))
    return roots


def resolve_root_id(
    roots: list[dict[str, Any]],
    requested: str | None,
    default_workspace: Path,
) -> str:
    if not roots:
        return "default"
    ids = {r["id"] for r in roots}
    if requested and requested in ids:
        return requested
    name = default_workspace.resolve().name.lstrip(".")
    if name in ids:
        return name
    return roots[0]["id"]


def workspace_for_root(
    roots: list[dict[str, Any]], root_id: str, fallback: Path
) -> Path:
    for r in roots:
        if r["id"] == root_id:
            return Path(r["path"])
    return fallback.resolve()
