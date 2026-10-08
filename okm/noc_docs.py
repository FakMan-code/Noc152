"""Docs NOC: documentación operativa generada desde Combinado.

Audiencia principal: operador NOC (qué es, qué hace cada pieza, deps, impacto).
OpenAPI/Scalar queda como contrato técnico secundario — no reemplaza esto.
"""

from __future__ import annotations

from typing import Any

from okm.humanize import is_noise_service
from okm.noc_combined import (
    _KNOWN_DEPS,
    _criticality,
    _story,
    build_noc_combined_system,
)
from okm.store import ExpedienteStore


def _deps_of(name: str) -> list[str]:
    return list(_KNOWN_DEPS.get(name.lower(), []))


def _used_by(name: str, all_names: list[str]) -> list[str]:
    key = name.lower()
    out: list[str] = []
    for src, targets in _KNOWN_DEPS.items():
        if key in {t.lower() for t in targets} and src in {n.lower() for n in all_names}:
            # resolve display name
            for n in all_names:
                if n.lower() == src:
                    out.append(n)
                    break
    return out


def build_noc_handbook(store: ExpedienteStore, workspace=None) -> dict[str, Any]:
    """Handbook JSON for /docs (operador NOC)."""
    graph = build_noc_combined_system(store, workspace=workspace)
    intro = graph.get("intro") or {}
    title = intro.get("title") or graph.get("title") or "Sistema"
    body = intro.get("body") or ""
    flow = ""
    what = intro.get("what_is_it") or ""
    # Prefer explicit flow from product story inside what_is_it / body
    if "→" in what or "->" in what:
        flow = what.split(".")[0].strip()

    services = [s for s in store.list_services() if not is_noise_service(s.name)]
    names = [s.name for s in services]
    # Self-map: use logical roles from graph nodes
    pieces: list[dict[str, Any]] = []
    for n in graph.get("nodes") or []:
        if n.get("kind") == "product":
            continue
        detail = (graph.get("details") or {}).get(n["id"]) or {}
        role = n.get("role") or n.get("label") or n["id"]
        svc_name = n.get("service_name") or ""
        crit = n.get("criticality") or (
            _criticality(svc_name) if svc_name and not str(svc_name).startswith("role:") else "media"
        )
        blurb = detail.get("summary") or ""
        deps_raw = []
        used_raw = []
        if svc_name and not str(svc_name).startswith("role:"):
            deps_raw = _deps_of(svc_name)
            used_raw = _used_by(svc_name, names)
            story = _story(svc_name)
            role = story["role"]
            blurb = story["blurb"]
        else:
            # logical self roles: deps from edges depends
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

        pieces.append(
            {
                "id": n["id"],
                "role": role,
                "service": svc_name if svc_name and not str(svc_name).startswith("role:") else None,
                "criticality": crit,
                "summary": blurb,
                "depends_on": deps_raw,
                "used_by": used_raw,
                "sources": detail.get("sources") or [],
                "watch": _watch_hints(role, crit, blurb),
            }
        )

    # Sort: alta first, then name
    order = {"alta": 0, "media": 1, "baja": 2}
    pieces.sort(key=lambda p: (order.get(str(p["criticality"]), 9), str(p["role"]).lower()))

    alta = [p for p in pieces if p.get("criticality") == "alta"]

    return {
        "audience": "noc",
        "audience_label": "Operador NOC",
        "title": title,
        "summary": body,
        "flow": flow or what,
        "how_to_read": {
            "map": (
                "El mapa Combinado muestra el producto y las piezas con roles humanos. "
                "Violeta = foco/hub. Gris = sin señal ops. Verde/amarillo/rojo = semáforo solo con monitoreo real."
            ),
            "edges": (
                "Una punta = un sentido. Dos puntas = ida/vuelta. "
                "Al seleccionar un nodo, las aristas ligadas se resaltan."
            ),
            "drill": "Click en un nodo para entrar a su capa. Atrás vuelve. Ampliar acerca la cámara.",
        },
        "pieces": pieces,
        "if_something_breaks": [
            {
                "when": f"Falla «{p['role']}»",
                "impact": p["summary"],
                "check": p["depends_on"] or ["revisar logs / salud del propio servicio"],
                "criticality": p["criticality"],
            }
            for p in alta
        ]
        or [
            {
                "when": "Sin piezas de criticidad alta mapeadas",
                "impact": "Revisar el mapa completo y el expediente del servicio afectado.",
                "check": ["Mapa Combinado", "Asistente con el nodo en foco"],
                "criticality": "media",
            }
        ],
        "for_agents": {
            "note": (
                "Esta página es la ficha operativa. El contrato HTTP (OpenAPI/Scalar) "
                "es secundario y a menudo viene incompleto si el repo no documentó schemas."
            ),
            "graph_engine": "combined",
            "ask": "POST /api/ask con focus_node del mapa",
            "openapi_docs": "/docs/api",
        },
        "links": {
            "map": "/",
            "api_contract": "/docs/api",
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
        "## Cómo leer el mapa",
        hand.get("how_to_read", {}).get("map", ""),
        hand.get("how_to_read", {}).get("edges", ""),
        "",
        "## Catálogo de piezas",
        "",
    ]
    for p in hand.get("pieces") or []:
        lines.append(f"### {p['role']} · criticidad {p['criticality']}")
        if p.get("service"):
            lines.append(f"- Servicio: `{p['service']}`")
        lines.append(f"- {p.get('summary') or ''}")
        if p.get("depends_on"):
            lines.append(f"- Depende de: {', '.join(p['depends_on'])}")
        if p.get("used_by"):
            lines.append(f"- Lo usan: {', '.join(p['used_by'])}")
        lines.append("")
    lines.append("## Si algo falla (prioridad)")
    for item in hand.get("if_something_breaks") or []:
        lines.append(f"- **{item['when']}** — {item['impact']}")
        check = item.get("check") or []
        if check:
            lines.append(f"  - Mirar: {', '.join(str(c) for c in check)}")
    return "\n".join(lines).strip() + "\n"
