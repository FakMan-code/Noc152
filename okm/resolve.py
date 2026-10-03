"""Generic service resolution from manifests — no hardcoded product names."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from okm.models import Service
from okm.store import stable_id


def _service_name_from_path(rel_dir: str, root_name: str) -> str:
    if not rel_dir or rel_dir in {".", ""}:
        return root_name
    return Path(rel_dir).name


def discover_services(
    relative_paths: list[str],
    *,
    source_uri: str,
    cfg: dict[str, Any],
) -> list[Service]:
    resolve_cfg = cfg.get("resolve", {})
    manifests = set(resolve_cfg.get("manifest_files", []))
    fallback = bool(resolve_cfg.get("fallback_root_service", True))

    root_name = Path(source_uri.rstrip("/").split("/")[-1]).stem or "root"
    if root_name.endswith(".git"):
        root_name = root_name[:-4]

    found_dirs: dict[str, Service] = {}

    for rel in relative_paths:
        p = Path(rel)
        if p.name not in manifests:
            continue
        parent = p.parent.as_posix()
        if parent == ".":
            parent = ""
        name = _service_name_from_path(parent, root_name)
        sid = stable_id("svc", source_uri, parent or "/", name)
        aliases = [name]
        if parent:
            aliases.append(parent)
        found_dirs[parent] = Service(
            service_id=sid,
            name=name,
            aliases=sorted(set(aliases)),
            root_path=parent or ".",
            summary=None,
        )

    if not found_dirs and fallback:
        sid = stable_id("svc", source_uri, "/", root_name)
        found_dirs[""] = Service(
            service_id=sid,
            name=root_name,
            aliases=[root_name],
            root_path=".",
            summary=None,
        )

    # Prefer deeper manifests as separate services; keep root if present
    return sorted(found_dirs.values(), key=lambda s: s.root_path)


def assign_service(path: str, services: list[Service]) -> Service | None:
    """Pick the most specific service whose root_path prefixes the file path."""
    best: Service | None = None
    best_len = -1
    norm = path.replace("\\", "/")
    for svc in services:
        root = svc.root_path.replace("\\", "/")
        if root in {".", ""}:
            # root service is fallback
            if best is None:
                best = svc
                best_len = 0
            continue
        prefix = root if root.endswith("/") else root + "/"
        if norm == root or norm.startswith(prefix):
            if len(root) > best_len:
                best = svc
                best_len = len(root)
    return best
