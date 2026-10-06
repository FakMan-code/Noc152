"""Project a validated Archify architecture JSON into the Noc152 3D graph.

Does not modify the Archify motor. Consumes its IR (components, connections,
boundaries, cards, views, sources, tags) and maps every field into the Three.js
payload so information is not cut.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from okm.health import health_legend, status_color, status_label
from okm.layout3d import apply_positions

# El color del nodo es salud (violeta/verde/amarillo/rojo), no el tipo Archify.
# El tipo sigue en facet / detalle.
ARCHIFY_TYPE_SIZE = {
    "frontend": 0.95,
    "backend": 1.05,
    "database": 1.0,
    "cloud": 1.0,
    "security": 0.95,
    "messagebus": 0.95,
    "external": 0.9,
}

VARIANT_EDGE = {
    "emphasis": "#64748b",
    "security": "#64748b",
    "dashed": "#475569",
    "default": "#3a3a3a",
}

# Hasta conectar alertas: solo principal vs ok.
_PRINCIPAL_IDS = frozenset({"client", "hub", "principal", "service"})


def load_archify_spec(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Archify spec must be a JSON object")
    if data.get("diagram_type") != "architecture":
        raise ValueError(f"unsupported diagram_type: {data.get('diagram_type')}")
    return data


def find_archify_spec(workspace: Path) -> Path | None:
    """Prefer workspace/archify/*.architecture.json, newest first."""
    root = workspace / "archify"
    if not root.is_dir():
        return None
    candidates = sorted(
        root.glob("*.architecture.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _layer_for(comp: dict[str, Any], boundaries: list[dict[str, Any]]) -> int:
    cid = comp["id"]
    in_pkg = False
    for b in boundaries:
        if cid in b.get("wraps", []) and b.get("kind") == "region":
            in_pkg = True
            break
    ctype = comp.get("type")
    if ctype == "external" and not in_pkg:
        return 0 if cid == "app" else 2
    if in_pkg:
        return 1
    return 1


def _membership(comp_id: str, boundaries: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for b in boundaries:
        if comp_id in b.get("wraps", []):
            out.append({"kind": str(b.get("kind", "region")), "label": str(b.get("label", ""))})
    return out


def _principal_id(components: list[dict[str, Any]], connections: list[dict[str, Any]]) -> str | None:
    """Pick the hub: explicit tag/id, else the most connected component."""
    for comp in components:
        cid = str(comp["id"])
        tag = str(comp.get("tag") or "").lower()
        if cid.lower() in _PRINCIPAL_IDS or tag in {"principal", "hub"}:
            return cid
    degree: dict[str, int] = {}
    for conn in connections:
        degree[str(conn["from"])] = degree.get(str(conn["from"]), 0) + 1
        degree[str(conn["to"])] = degree.get(str(conn["to"]), 0) + 1
    if not degree:
        return str(components[0]["id"]) if components else None
    return max(degree, key=degree.get)


def _node_status(comp_id: str, principal_id: str | None, override: str | None = None) -> str:
    """Health for a node. Overrides reserved for future ops/alerts wiring."""
    if override in {"principal", "ok", "alert", "failing"}:
        return override
    if principal_id and comp_id == principal_id:
        return "principal"
    return "ok"


def archify_to_graph(spec: dict[str, Any], *, engine: str = "archify") -> dict[str, Any]:
    meta = spec.get("meta") or {}
    components = list(spec.get("components") or [])
    connections = list(spec.get("connections") or [])
    boundaries = list(spec.get("boundaries") or [])
    cards = list(spec.get("cards") or [])
    views = list(meta.get("views") or [])
    repo = meta.get("repository") or {}

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    details: dict[str, dict[str, Any]] = {}
    principal_id = _principal_id(components, connections)
    # Optional future map: component_id → alert|failing from ops producers.
    health_overrides: dict[str, str] = dict(meta.get("health") or {})

    for comp in components:
        cid = str(comp["id"])
        ctype = str(comp.get("type") or "backend")
        status = _node_status(cid, principal_id, health_overrides.get(cid))
        color = status_color(status)
        label = str(comp.get("label") or cid)
        sub = str(comp.get("sublabel") or "")
        tag = comp.get("tag")
        sources = list(comp.get("sources") or [])
        membership = _membership(cid, boundaries)
        layer = _layer_for(comp, boundaries)
        display = label if len(label) <= 26 else label[:25] + "…"
        size = ARCHIFY_TYPE_SIZE.get(ctype, 1.0)
        if status == "principal":
            size = max(size, 1.35)

        nodes.append(
            {
                "id": cid,
                "kind": ctype,
                "label": display,
                "layer": layer,
                "color": color,
                "size": size,
                "facet": ctype,
                "health": status,
                "health_label": status_label(status),
                "archify_type": ctype,
                "tag": tag,
                "sublabel": sub,
                "boundaries": [m["label"] for m in membership],
            }
        )

        source_items = []
        for src in sources:
            path = src.get("path", "")
            line = src.get("line")
            end = src.get("end_line")
            lab = src.get("label") or path
            ref = path
            if line:
                ref = f"{path}:L{line}" + (f"-{end}" if end and end != line else "")
            source_items.append({"statement": f"{lab} — {ref}", "kind": "observed"})

        boundary_items = [
            {"statement": f"{m['kind']}: {m['label']}", "kind": "inferred"} for m in membership
        ]
        sections: list[dict[str, Any]] = []
        if source_items:
            sections.append({"title": "Fuentes (Archify)", "items": source_items})
        if boundary_items:
            sections.append({"title": "Boundaries", "items": boundary_items})
        if tag:
            sections.append(
                {"title": "Tag", "items": [{"statement": str(tag), "kind": "observed"}]}
            )

        details[cid] = {
            "title": label,
            "kind": ctype,
            "kind_label": ctype,
            "subtitle": " · ".join(x for x in [sub, ctype, status_label(status)] if x),
            "summary": sub or label,
            "meta": {
                "estado": status_label(status),
                "tipo": ctype,
                "id": cid,
                **({"tag": tag} if tag else {}),
            },
            "sections": sections,
            "facet": ctype,
            "archify": {
                "type": ctype,
                "tag": tag,
                "sublabel": sub,
                "sources": sources,
                "boundaries": membership,
                "pos": comp.get("pos"),
                "size": comp.get("size"),
                "health": status,
            },
        }

    for conn in connections:
        src = str(conn["from"])
        dst = str(conn["to"])
        eid = str(conn.get("id") or f"{src}->{dst}")
        variant = str(conn.get("variant") or "default")
        label = str(conn.get("label") or "")
        edges.append(
            {
                "id": eid,
                "source": src,
                "target": dst,
                "kind": variant if variant != "default" else "relates",
                "label": label,
                "variant": variant,
                "color": VARIANT_EDGE.get(variant, VARIANT_EDGE["default"]),
                "archify": {
                    k: conn[k]
                    for k in (
                        "fromSide",
                        "toSide",
                        "route",
                        "via",
                        "labelAt",
                        "labelDx",
                        "labelDy",
                        "width",
                    )
                    if k in conn
                },
            }
        )

    apply_positions(nodes, edges, seed=152)

    title = str(meta.get("title") or "Archify")
    types = sorted({str(c.get("type") or "backend") for c in components})
    return {
        "title": "Noc152",
        "engine": engine,
        "locale": "es",
        "view": "archify",
        "intro": {
            "title": title,
            "body": f"{len(components)} componentes · {len(connections)} relaciones · IR Archify",
            "what_is_it": "",
            "node_legend": health_legend(),
            "tips": [],
        },
        "service": {
            "id": "archify",
            "name": title,
            "summary": title,
        },
        "nodes": nodes,
        "edges": edges,
        "details": details,
        "coverage": {},
        "facets": [{"id": t, "label": t, "hint": f"tipo Archify · {t}"} for t in types],
        "trace_paths": [],
        "controls": {
            "orbit": "arrastrar",
            "zoom": "rueda",
            "pan": "click-rueda",
            "select": "click en nodo",
            "expand": "doble click o Ampliar",
            "filter": "tipos Archify / vistas",
        },
        "archify": {
            "meta": meta,
            "repository": repo,
            "boundaries": boundaries,
            "cards": cards,
            "views": views,
            "connections": connections,
            "component_count": len(components),
            "connection_count": len(connections),
            "spec_title": title,
            "principal_id": principal_id,
            "health_legend": health_legend(),
        },
    }
