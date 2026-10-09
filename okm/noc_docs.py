"""Docs NOC: documentación operativa generada desde Combinado.

Audiencia principal: operador NOC (qué es, qué hace cada pieza, deps, impacto).
OpenAPI/Scalar queda como contrato técnico secundario — no reemplaza esto.

Estilo DeepWiki: overview + flujo + piezas + archivos clave con deep-link.
"""

from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import quote

from okm.humanize import is_noise_service
from okm.noc_combined import (
    _KNOWN_DEPS,
    _criticality,
    _story,
    build_noc_combined_system,
)
from okm.node_sources import NODE_SOURCE_MAP
from okm.store import ExpedienteStore, Service

_CODE_SUFFIXES = (
    ".py",
    ".go",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".java",
    ".rs",
    ".cs",
    ".rb",
    ".html",
)


def _deps_of(name: str) -> list[str]:
    return list(_KNOWN_DEPS.get(name.lower(), []))


def _used_by(name: str, all_names: list[str]) -> list[str]:
    key = name.lower()
    out: list[str] = []
    for src, targets in _KNOWN_DEPS.items():
        if key in {t.lower() for t in targets} and src in {n.lower() for n in all_names}:
            for n in all_names:
                if n.lower() == src:
                    out.append(n)
                    break
    return out


def _q(value: str | None) -> str:
    return quote(value or "", safe="")


def _with_root(path: str, root_id: str | None) -> str:
    if not root_id:
        return path
    sep = "&" if "?" in path else "?"
    if "root=" in path:
        return path
    return f"{path}{sep}root={_q(root_id)}"


def _file_ref(
    path: str,
    *,
    line: int | None = None,
    focus: str | None = None,
    root_id: str | None = None,
    role: str = "anexo",
) -> dict[str, Any]:
    rel = path.replace("\\", "/")
    url = f"/api/source/file?path={_q(rel)}"
    if focus:
        url += f"&focus={_q(focus)}"
    url = _with_root(url, root_id)
    ref = f"{rel}:L{line}" if line else rel
    return {
        "path": rel,
        "line": line,
        "ref": ref,
        "role": role,
        "focus": focus,
        "url": url,
    }


def _mapped_sources(focus_id: str | None, role_label: str | None) -> list[str]:
    keys: list[str] = []
    if focus_id:
        keys.append(focus_id.lower())
        if ":" in focus_id:
            keys.append(focus_id.split(":")[-1].lower())
    if role_label:
        keys.append(role_label.lower())
    seen: list[str] = []
    for k in keys:
        for rel in NODE_SOURCE_MAP.get(k, []):
            if rel not in seen:
                seen.append(rel)
    return seen


def _evidence_key_files(
    store: ExpedienteStore,
    svc: Service,
    *,
    focus: str | None,
    root_id: str | None,
    limit: int = 4,
) -> list[dict[str, Any]]:
    """Top evidence paths under the service folder (DeepWiki-style key files)."""
    prefix = (svc.root_path or svc.name or "").replace("\\", "/").strip("/")
    counts: Counter[str] = Counter()
    first_line: dict[str, int] = {}
    for ev in store.list_evidence():
        path = (ev.path or "").replace("\\", "/")
        if not path or path.endswith("/"):
            continue
        if prefix:
            if not (path == prefix or path.startswith(prefix + "/")):
                continue
        lower = path.lower()
        base = lower.rsplit("/", 1)[-1]
        if lower.endswith((".md", ".txt", ".license", ".gitignore")):
            continue
        if base in {"dockerfile", "makefile", "gemfile"}:
            continue
        counts[path] += 1
        loc = ev.locator.to_json() if ev.locator else {}
        line = loc.get("start_line") or loc.get("line")
        if line is not None and path not in first_line:
            try:
                first_line[path] = int(line)
            except (TypeError, ValueError):
                pass

    def sort_key(item: tuple[str, int]) -> tuple[int, int, str]:
        path, n = item
        lower = path.lower()
        base = lower.rsplit("/", 1)[-1]
        if base in {"dockerfile", "makefile", "gemfile"} or lower.endswith(
            (".dockerfile",)
        ):
            tier = 2
        elif any(lower.endswith(s) for s in _CODE_SUFFIXES):
            tier = 0
        elif lower.endswith((".json", ".yaml", ".yml", ".toml", ".proto")):
            tier = 1
        else:
            tier = 3
        return (tier, -n, path)

    ranked = sorted(counts.items(), key=sort_key)
    out: list[dict[str, Any]] = []
    for i, (path, _n) in enumerate(ranked[:limit]):
        out.append(
            _file_ref(
                path,
                line=first_line.get(path),
                focus=focus,
                root_id=root_id,
                role="primary" if i == 0 else "anexo",
            )
        )
    return out


def _sources_to_files(
    sources: list[Any],
    *,
    focus: str | None,
    root_id: str | None,
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for i, src in enumerate(sources):
        if isinstance(src, str):
            files.append(
                _file_ref(
                    src,
                    focus=focus,
                    root_id=root_id,
                    role="primary" if i == 0 else "anexo",
                )
            )
            continue
        if isinstance(src, dict):
            path = str(src.get("path") or src.get("file") or "")
            if not path:
                continue
            line = src.get("line") or src.get("start_line")
            try:
                line_i = int(line) if line is not None else None
            except (TypeError, ValueError):
                line_i = None
            files.append(
                _file_ref(
                    path,
                    line=line_i,
                    focus=focus or src.get("focus"),
                    root_id=root_id,
                    role="primary" if i == 0 else "anexo",
                )
            )
    return files


def build_noc_handbook(
    store: ExpedienteStore,
    workspace=None,
    root_id: str | None = None,
) -> dict[str, Any]:
    """Handbook JSON for /docs (operador NOC)."""
    graph = build_noc_combined_system(store, workspace=workspace)
    intro = graph.get("intro") or {}
    title = intro.get("title") or graph.get("title") or "Sistema"
    body = intro.get("body") or ""
    flow = ""
    what = intro.get("what_is_it") or ""
    if "→" in what or "->" in what:
        flow = what.split(".")[0].strip()

    services = [s for s in store.list_services() if not is_noise_service(s.name)]
    names = [s.name for s in services]
    by_name = {s.name.lower(): s for s in services}

    pieces: list[dict[str, Any]] = []
    for n in graph.get("nodes") or []:
        if n.get("kind") == "product":
            continue
        detail = (graph.get("details") or {}).get(n["id"]) or {}
        role = n.get("role") or n.get("label") or n["id"]
        svc_name = n.get("service_name") or ""
        is_logical = not svc_name or str(svc_name).startswith("role:")
        crit = n.get("criticality") or (
            _criticality(svc_name) if not is_logical else "media"
        )
        blurb = detail.get("summary") or ""
        deps_raw: list[str] = []
        used_raw: list[str] = []
        focus = str(n["id"])
        key_files: list[dict[str, Any]] = []

        if not is_logical:
            deps_raw = _deps_of(svc_name)
            used_raw = _used_by(svc_name, names)
            story = _story(svc_name)
            role = story["role"]
            blurb = story["blurb"]
            svc = by_name.get(str(svc_name).lower())
            if svc is not None:
                key_files = _evidence_key_files(
                    store, svc, focus=focus, root_id=root_id, limit=4
                )
        else:
            for e in graph.get("edges") or []:
                if e.get("kind") != "depends":
                    continue
                if e.get("source") == n["id"]:
                    tgt = next(
                        (x for x in graph["nodes"] if x["id"] == e["target"]),
                        None,
                    )
                    if tgt:
                        deps_raw.append(tgt.get("label") or tgt["id"])
                if e.get("target") == n["id"]:
                    src = next(
                        (x for x in graph["nodes"] if x["id"] == e["source"]),
                        None,
                    )
                    if src:
                        used_raw.append(src.get("label") or src["id"])
            mapped = _mapped_sources(focus, str(role))
            raw_sources = detail.get("sources") or mapped
            key_files = _sources_to_files(
                list(raw_sources), focus=focus, root_id=root_id
            )

        pieces.append(
            {
                "id": n["id"],
                "role": role,
                "service": None if is_logical else svc_name,
                "criticality": crit,
                "summary": blurb,
                "depends_on": deps_raw,
                "used_by": used_raw,
                "sources": [f["path"] for f in key_files],
                "key_files": key_files,
                "watch": _watch_hints(role, crit, blurb),
            }
        )

    order = {"alta": 0, "media": 1, "baja": 2}
    pieces.sort(key=lambda p: (order.get(str(p["criticality"]), 9), str(p["role"]).lower()))

    alta = [p for p in pieces if p.get("criticality") == "alta"]

    # Overview key files (dedup, primary first) — DeepWiki “archivos más relevantes”
    seen_paths: set[str] = set()
    overview_files: list[dict[str, Any]] = []
    for p in pieces:
        for f in p.get("key_files") or []:
            path = f.get("path")
            if not path or path in seen_paths:
                continue
            seen_paths.add(path)
            overview_files.append({**f, "piece": p["role"]})
            if len(overview_files) >= 12:
                break
        if len(overview_files) >= 12:
            break

    return {
        "audience": "noc",
        "audience_label": "Operador NOC",
        "title": title,
        "summary": body,
        "flow": flow or what,
        "root": root_id,
        "how_to_read": {
            "map": (
                "El mapa Combinado muestra el producto y las piezas con roles humanos. "
                "Violeta = foco/hub. Gris = sin señal ops. Verde/amarillo/rojo = semáforo solo con monitoreo real."
            ),
            "edges": (
                "Una punta = un sentido. Dos puntas = ida/vuelta. "
                "Al seleccionar un nodo, las aristas ligadas se resaltan."
            ),
            "drill": (
                "Click en un nodo para entrar a su capa. Atrás vuelve. "
                "Archivos clave abren el código real del repo de esta raíz."
            ),
        },
        "key_files": overview_files,
        "pieces": pieces,
        "if_something_breaks": [
            {
                "when": f"Falla «{p['role']}»",
                "impact": p["summary"],
                "check": p["depends_on"] or ["revisar logs / salud del propio servicio"],
                "criticality": p["criticality"],
                "key_files": (p.get("key_files") or [])[:2],
            }
            for p in alta
        ]
        or [
            {
                "when": "Sin piezas de criticidad alta mapeadas",
                "impact": "Revisar el mapa completo y el expediente del servicio afectado.",
                "check": ["Mapa Combinado", "Asistente con el nodo en foco"],
                "criticality": "media",
                "key_files": overview_files[:3],
            }
        ],
        "for_agents": {
            "note": (
                "Esta página es la ficha operativa. El contrato HTTP (OpenAPI/Scalar) "
                "es secundario y a menudo viene incompleto si el repo no documentó schemas."
            ),
            "graph_engine": "combined",
            "ask": "POST /api/ask con focus_node del mapa y root de la raíz activa",
            "openapi_docs": _with_root("/docs/api", root_id),
        },
        "links": {
            "map": _with_root("/", root_id) if root_id else "/",
            "api_contract": _with_root("/docs/api", root_id),
        },
    }


def _watch_hints(role: str, crit: str, blurb: str) -> list[str]:
    hints = [
        f"Si «{role}» no responde, el usuario siente: {blurb.split('.')[0]}.",
    ]
    if crit == "alta":
        hints.append("Criticidad alta: priorizar en triage y escalar según runbook del país.")
    return hints


def render_noc_handbook_markdown(hand: dict[str, Any]) -> str:
    """Markdown export (agente / Confluence)."""
    lines = [
        f"# {hand['title']} — ficha NOC",
        "",
        f"**Audiencia:** {hand.get('audience_label', 'Operador NOC')}",
        "",
        "## Qué es",
        hand.get("summary") or "",
        "",
        "## Flujo",
        hand.get("flow") or "",
        "",
    ]
    if hand.get("key_files"):
        lines.append("## Archivos clave")
        lines.append("")
        for f in hand["key_files"]:
            piece = f" · {f['piece']}" if f.get("piece") else ""
            lines.append(f"- `{f.get('ref') or f.get('path')}`{piece}")
        lines.append("")
    lines.extend(
        [
            "## Cómo leer el mapa",
            hand.get("how_to_read", {}).get("map", ""),
            hand.get("how_to_read", {}).get("edges", ""),
            "",
            "## Catálogo de piezas",
            "",
        ]
    )
    for p in hand.get("pieces") or []:
        lines.append(f"### {p['role']} · criticidad {p['criticality']}")
        if p.get("service"):
            lines.append(f"- Servicio: `{p['service']}`")
        lines.append(f"- {p.get('summary') or ''}")
        if p.get("depends_on"):
            lines.append(f"- Depende de: {', '.join(p['depends_on'])}")
        if p.get("used_by"):
            lines.append(f"- Lo usan: {', '.join(p['used_by'])}")
        if p.get("key_files"):
            refs = ", ".join(f"`{f.get('ref') or f['path']}`" for f in p["key_files"])
            lines.append(f"- Archivos: {refs}")
        lines.append("")
    lines.append("## Si algo falla (prioridad)")
    for item in hand.get("if_something_breaks") or []:
        lines.append(f"- **{item['when']}** — {item['impact']}")
        check = item.get("check") or []
        if check:
            lines.append(f"  - Mirar: {', '.join(str(c) for c in check)}")
    return "\n".join(lines).strip() + "\n"
