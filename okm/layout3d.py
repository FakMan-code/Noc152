"""3D graph layout for Noc152 — NumPy force simulation over the expediente.

NumPy ideas used here (good practice targets):
  - ndarray of shape (N, 3) for XYZ positions
  - broadcasting for all-pairs repulsion
  - boolean masks / fancy indexing for edges
  - vector normalization with a safe epsilon
"""

from __future__ import annotations

from typing import Any

import numpy as np

from okm.health import NODE_COLOR, node_color_for_claim, service_health
from okm.humanize import (
    FACET_ES,
    brief_intro,
    facet_filter_label,
    facet_label,
    human_claim,
    human_summary,
    is_noise_service,
    kind_label,
    source_display_name,
    system_intro,
)
from okm.models import Claim, EpistemicKind, Facet, Service
from okm.store import ExpedienteStore

# No van como esferas de claim: imports son ruido; packages ya salen como nodos dep:*
_NOISY = {
    "imports_module",
    "references_url",
    "depends_on_package",
    "requires_package",
}


def _clip_label(text: str, n: int = 26) -> str:
    text = text.strip()
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def _claim_label(claim: Claim) -> str:
    if claim.object_value:
        return _clip_label(claim.object_value.replace("pip:", ""), 22)
    if claim.predicate in _PRED_SHORT:
        return _PRED_SHORT[claim.predicate]
    return _clip_label(human_claim(claim), 22)


_PRED_SHORT = {
    "package_name": "nombre",
    "documented_title": "título",
    "likely_purpose": "propósito",
    "facet_uncovered": "sin señales",
    "facet_incomplete": "incompleto",
    "depends_on_package": "depende",
    "requires_package": "requiere",
}


def _evidence_items(store: ExpedienteStore, claim: Claim, *, open_full: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for eid in claim.evidence_ids[:2]:
        ev = store.get_evidence(eid)
        if not ev:
            continue
        excerpt = store.open_excerpt(eid) if open_full else (ev.excerpt or "")
        out.append(
            {
                "id": ev.evidence_id,
                "ref": ev.openable_ref(),
                "excerpt": (excerpt or "")[:400],
            }
        )
    return out


def _claim_detail(store: ExpedienteStore, claim: Claim) -> dict[str, Any]:
    text = human_claim(claim)
    sections = []
    ev = _evidence_items(store, claim, open_full=True)
    if ev:
        sections.append({"title": "Dónde lo vimos", "items": ev})
    return {
        "title": _clip_label(text, 72),
        "kind": claim.kind.value,
        "kind_label": kind_label(claim.kind.value),
        "subtitle": f"{facet_label(claim.facet.value)} · {kind_label(claim.kind.value)}",
        "summary": text,
        "meta": {
            "confianza": claim.confidence,
            "origen": claim.producer,
        },
        "sections": sections,
        "facet": claim.facet.value,
    }


def build_system_graph(store: ExpedienteStore) -> dict[str, Any]:
    """Top-level microservices map — one node per real service."""
    run = store.latest_run() or {}
    source_uri = run.get("source_uri")
    system_name = source_display_name(source_uri)
    services = [s for s in store.list_services() if not is_noise_service(s.name)]
    # Más claims primero (más “denso” operacionalmente), luego nombre
    services.sort(
        key=lambda s: (-len(store.claims_for(s.service_id)), s.name.lower()),
    )

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    details: dict[str, dict[str, Any]] = {}
    trace_paths: list[list[str]] = []

    hub_id = "sys:root"
    nodes.append(
        {
            "id": hub_id,
            "kind": "service",
            "label": system_name,
            "layer": 0,
            "color": NODE_COLOR["hub"],
            "size": 1.55,
            "facet": None,
            "service_name": None,
            "health": "hub",
        }
    )
    details[hub_id] = {
        "title": system_name,
        "kind": "service",
        "kind_label": "sistema",
        "subtitle": "Hub del source ingerido",
        "summary": (
            f"Mapa de servicios detectados en «{system_name}». "
            "Cada nodo alrededor es un servicio real del repo. "
            "Click en uno para ver su expediente completo."
        ),
        "meta": {
            "fuente": source_uri or "local",
            "servicios": len(services),
        },
        "sections": [
            {
                "title": "Servicios del mapa",
                "items": [
                    {
                        "statement": human_summary(s),
                        "kind": "observed",
                        "open_service": s.name,
                    }
                    for s in services
                ],
            }
        ],
        "facet": None,
    }

    for s in services:
        nid = f"svc:{s.service_id}"
        cov = store.coverage_for(s.service_id)
        obs = sum(v.get("observed", 0) for v in cov.values())
        gap = sum(v.get("gap", 0) for v in cov.values())
        health = service_health(store, s)
        short = s.name
        if short.lower().endswith("service") and len(short) > 7:
            short = short[: -len("service")]
        nodes.append(
            {
                "id": nid,
                "kind": "service",
                "label": short or s.name,
                "layer": 1,
                "color": health["color"],
                "size": 1.0,
                "facet": None,
                "service_name": s.name,
                "health": health["health"],
            }
        )
        edges.append({"source": hub_id, "target": nid, "kind": "contains"})
        trace_paths.append([hub_id, nid])
        details[nid] = {
            "title": s.name,
            "kind": "service",
            "kind_label": "microservicio",
            "subtitle": f"Estado: {health['label']}",
            "summary": f"{human_summary(s)} {health['reason']}",
            "meta": {
                "salud": health["label"],
                "ruta": s.root_path,
                "hallazgos_vistos": obs,
                "huecos": gap,
            },
            "sections": [],
            "facet": None,
            "open_service": s.name,
        }

    positions = layout_force_3d(nodes, edges, seed=152)
    for node, xyz in zip(nodes, positions):
        node["x"], node["y"], node["z"] = (float(xyz[0]), float(xyz[1]), float(xyz[2]))

    names = [s.name for s in services]
    return {
        "title": "Noc152",
        "engine": "numpy-force-3d",
        "locale": "es",
        "view": "system",
        "intro": system_intro(source_uri=source_uri, service_names=names),
        "service": {
            "id": "system",
            "name": "__system__",
            "summary": "Mapa de servicios.",
        },
        "nodes": nodes,
        "edges": edges,
        "details": details,
        "coverage": {},
        "facets": [],
        "trace_paths": trace_paths,
        "controls": {
            "orbit": "arrastrar",
            "zoom": "rueda",
            "pan": "click-rueda",
            "select": "click en nodo",
            "expand": "doble click o Ampliar",
            "filter": "filtros (vista servicio)",
        },
    }


def build_scene_graph(store: ExpedienteStore, service: Service) -> dict[str, Any]:
    """Build a navigable node/edge graph + detail cards from the expediente."""
    claims = store.claims_for(service.service_id)
    relations = store.relations_for(service.service_id)
    coverage = store.coverage_for(service.service_id)
    run = store.latest_run() or {}
    source_uri = run.get("source_uri")

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    details: dict[str, dict[str, Any]] = {}
    trace_paths: list[list[str]] = []

    svc_id = f"svc:{service.service_id}"
    summary_es = human_summary(service)
    health = service_health(store, service)
    nodes.append(
        {
            "id": svc_id,
            "kind": "service",
            "label": service.name,
            "layer": 0,
            "color": health["color"],
            "size": 1.4,
            "facet": None,
            "health": health["health"],
        }
    )
    details[svc_id] = {
        "title": service.name,
        "kind": "service",
        "kind_label": kind_label("service"),
        "subtitle": f"Estado: {health['label']}",
        "summary": f"{summary_es} {health['reason']}",
        "meta": {
            "salud": health["label"],
            "fuente": source_display_name(source_uri),
            "aliases": ", ".join(
                a for a in (service.aliases or []) if "proyecto" not in a.lower()
            )
            or service.name,
        },
        "sections": [],
        "facet": None,
    }

    facet_ids: dict[str, str] = {}
    for facet in Facet:
        meta = FACET_ES[facet.value]
        fid = f"facet:{facet.value}"
        facet_ids[facet.value] = fid
        cov = coverage.get(facet.value, {"observed": 0, "inferred": 0, "gap": 0})
        nodes.append(
            {
                "id": fid,
                "kind": "facet",
                "label": meta["label"],
                "layer": 1,
                "color": NODE_COLOR["facet"],
                "size": 1.05,
                "facet": facet.value,
            }
        )
        edges.append({"source": svc_id, "target": fid, "kind": "has_facet"})
        trace_paths.append([svc_id, fid])

        facet_claims = [c for c in claims if c.facet == facet]
        sections: list[dict[str, Any]] = []
        for kind in (EpistemicKind.OBSERVED, EpistemicKind.INFERRED, EpistemicKind.GAP):
            subset = [c for c in facet_claims if c.kind == kind]
            items = []
            for c in subset:
                if c.predicate in _NOISY:
                    continue
                if len(items) >= 8:
                    break
                items.append(
                    {
                        "id": c.claim_id,
                        "statement": human_claim(c),
                        "kind": c.kind.value,
                        "gap_reason": c.gap_reason,
                        "evidence": _evidence_items(store, c),
                    }
                )
            if items:
                sections.append({"title": kind_label(kind.value), "items": items})

        details[fid] = {
            "title": meta["label"],
            "kind": "facet",
            "kind_label": kind_label("facet"),
            "subtitle": meta["hint"],
            "summary": (
                f"{meta['guide']} "
                f"Hoy: {cov['observed']} visto(s), {cov['inferred']} probable(s), "
                f"{cov['gap']} hueco(s)."
            ),
            "meta": {
                "visto": cov["observed"],
                "probable": cov["inferred"],
                "huecos": cov["gap"],
            },
            "sections": sections,
            "facet": facet.value,
        }

        # More claim nodes per facet (2–4), still readable
        picks: list[Claim] = []
        for kind in (EpistemicKind.OBSERVED, EpistemicKind.INFERRED, EpistemicKind.GAP):
            for c in facet_claims:
                if c.kind != kind or c.predicate in _NOISY:
                    continue
                if c in picks:
                    continue
                picks.append(c)
                if len(picks) >= (2 if facet != Facet.TOPOLOGY else 3):
                    break
            if len(picks) >= (2 if facet != Facet.TOPOLOGY else 3):
                break

        for pick in picks:
            cid = f"claim:{pick.claim_id}"
            if any(n["id"] == cid for n in nodes):
                continue
            kind_ui, color = node_color_for_claim(pick)
            health_ui = (
                "failing"
                if kind_ui == "failing"
                else "alert"
                if kind_ui == "alert"
                else "ok"
            )
            nodes.append(
                {
                    "id": cid,
                    "kind": kind_ui,
                    "label": _claim_label(pick),
                    "layer": 2,
                    "color": color,
                    "size": 0.7,
                    "facet": facet.value,
                    "health": health_ui,
                }
            )
            edges.append({"source": fid, "target": cid, "kind": "shows"})
            details[cid] = _claim_detail(store, pick)
            if kind_ui == "failing":
                details[cid]["subtitle"] = "Estado: roto · " + details[cid].get("subtitle", "")
            elif kind_ui == "alert":
                details[cid]["subtitle"] = "Alerta a revisar · " + details[cid].get("subtitle", "")
            elif kind_ui == "gap":
                details[cid]["subtitle"] = "Hueco informativo · " + details[cid].get("subtitle", "")
            trace_paths.append([svc_id, fid, cid])

    # Dependencies under topology (observed first, then name)
    topo_id = facet_ids["topology"]
    pkg_rels = [r for r in relations if r.kind == "depends_on_package"]
    pkg_rels.sort(
        key=lambda r: (
            0 if r.epistemic == EpistemicKind.OBSERVED else 1,
            r.to_ref.lower(),
        )
    )
    for r in pkg_rels[:14]:
        label = r.to_ref.replace("pip:", "")
        did = f"dep:{label}"
        if any(n["id"] == did for n in nodes):
            continue
        nodes.append(
            {
                "id": did,
                "kind": "dependency",
                "label": _clip_label(label, 20),
                "layer": 2,
                "color": NODE_COLOR["dependency"],
                "size": 0.78,
                "facet": "topology",
            }
        )
        edges.append({"source": topo_id, "target": did, "kind": "depends_on"})
        details[did] = {
            "title": label,
            "kind": "dependency",
            "kind_label": kind_label("dependency"),
            "subtitle": "Paquete del que depende",
            "summary": (
                f"«{service.name}» declara que usa «{label}». "
                f"Lo marcamos como {kind_label(r.epistemic.value)}."
            ),
            "meta": {
                "referencia": r.to_ref,
                "confianza": kind_label(r.epistemic.value),
            },
            "sections": [],
            "facet": "topology",
        }
        trace_paths.append([svc_id, topo_id, did])

    positions = layout_force_3d(nodes, edges, seed=152)
    for node, xyz in zip(nodes, positions):
        node["x"], node["y"], node["z"] = (float(xyz[0]), float(xyz[1]), float(xyz[2]))

    return {
        "title": "Noc152",
        "engine": "numpy-force-3d",
        "locale": "es",
        "view": "service",
        "intro": brief_intro(service, source_uri=source_uri),
        "service": {
            "id": service.service_id,
            "name": service.name,
            "summary": summary_es,
            "summary_raw": service.summary,
            "health": health["health"],
            "health_label": health["label"],
        },
        "nodes": nodes,
        "edges": edges,
        "details": details,
        "coverage": coverage,
        "facets": [
            {
                "id": f.value,
                "label": facet_filter_label(f.value),
                "hint": FACET_ES[f.value]["hint"],
            }
            for f in Facet
        ],
        "trace_paths": trace_paths[:24],
        "controls": {
            "orbit": "arrastrar",
            "zoom": "rueda",
            "pan": "click-rueda",
            "select": "click en nodo",
            "expand": "doble click o Ampliar",
            "filter": "filtros",
        },
    }


def apply_positions(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    seed: int = 152,
) -> None:
    positions = layout_force_3d(nodes, edges, seed=seed)
    for node, xyz in zip(nodes, positions):
        node["x"], node["y"], node["z"] = (float(xyz[0]), float(xyz[1]), float(xyz[2]))


def layout_force_3d(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    iterations: int = 220,
    seed: int = 152,
) -> np.ndarray:
    """Spring-embedder in 3D. Returns positions shape (N, 3)."""
    n = len(nodes)
    if n == 0:
        return np.zeros((0, 3), dtype=np.float64)

    rng = np.random.default_rng(seed)
    pos = rng.normal(0.0, 0.8, size=(n, 3))
    layers = np.array([int(node.get("layer", 0)) for node in nodes], dtype=np.float64)
    pos[:, 1] += layers * 1.4

    id_to_i = {node["id"]: i for i, node in enumerate(nodes)}
    edge_idx = [
        (id_to_i[e["source"]], id_to_i[e["target"]])
        for e in edges
        if e["source"] in id_to_i and e["target"] in id_to_i
    ]

    if edge_idx:
        src = np.array([a for a, _ in edge_idx], dtype=np.int64)
        dst = np.array([b for _, b in edge_idx], dtype=np.int64)
        ideal = 1.35 + 0.55 * np.abs(layers[src] - layers[dst])
    else:
        src = dst = ideal = np.array([], dtype=np.int64)

    target_r = 0.2 + layers * 2.1

    for step in range(iterations):
        temp = 0.85 * (1.0 - step / iterations) + 0.05

        delta = pos[:, None, :] - pos[None, :, :]
        dist2 = np.sum(delta * delta, axis=-1) + 1e-6
        np.fill_diagonal(dist2, np.inf)
        inv = 1.0 / dist2
        force = np.sum(delta * inv[:, :, None] * 0.55, axis=1)

        if src.size:
            dvec = pos[dst] - pos[src]
            dlen = np.linalg.norm(dvec, axis=1) + 1e-6
            stretch = (dlen - ideal) / dlen
            spring = dvec * stretch[:, None] * 0.12
            np.add.at(force, src, spring)
            np.add.at(force, dst, -spring)

        force -= pos * 0.02
        radial = np.linalg.norm(pos[:, [0, 2]], axis=1) + 1e-6
        radial_err = (target_r - radial) / radial
        force[:, 0] += pos[:, 0] * radial_err * 0.04
        force[:, 2] += pos[:, 2] * radial_err * 0.04
        force[layers == 0] *= 0.25

        speed = np.linalg.norm(force, axis=1, keepdims=True) + 1e-6
        force = force / speed * np.minimum(speed, temp)
        pos += force

    pos -= pos.mean(axis=0)
    span = np.max(np.linalg.norm(pos, axis=1))
    if span > 1e-6:
        pos *= 5.5 / span
    return pos
