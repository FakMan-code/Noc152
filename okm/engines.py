"""Select which knowledge graph to project into the 3D viewer.

Engines are the build backends. User-facing names live in okm.projections.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from okm.archify_graph import build_archify_scene
from okm.layout3d import build_scene_graph, build_system_graph
from okm.models import Service
from okm.noc_combined import build_noc_combined_service, build_noc_combined_system
from okm.projections import (
    _annotate,
    available_projections,
    build_architecture_projection,
    build_flows_graph,
    build_network_projection,
    build_services_projection,
    build_technologies_graph,
    get_projection,
)
from okm.store import ExpedienteStore


class GraphEngine(str, Enum):
    """Backend build keys (kept for compat). Prefer projection ids in the UI."""

    ARCHIFY = "archify"
    COMBINED = "combined"
    NOC152 = "noc152"
    OPENAPI = "openapi"
    SERVICES = "services"
    TECHNOLOGIES = "technologies"
    NETWORK = "network"
    FLOWS = "flows"


_ALIASES: dict[str, GraphEngine] = {
    "general": GraphEngine.COMBINED,
    "combined": GraphEngine.COMBINED,
    "combinado": GraphEngine.COMBINED,
    "services": GraphEngine.SERVICES,
    "servicios": GraphEngine.SERVICES,
    "architecture": GraphEngine.ARCHIFY,
    "archify": GraphEngine.ARCHIFY,
    "arquitectura": GraphEngine.ARCHIFY,
    "technologies": GraphEngine.TECHNOLOGIES,
    "tools": GraphEngine.TECHNOLOGIES,
    "herramientas": GraphEngine.TECHNOLOGIES,
    "network": GraphEngine.NETWORK,
    "red": GraphEngine.NETWORK,
    "openapi": GraphEngine.NETWORK,
    "flows": GraphEngine.FLOWS,
    "flujos": GraphEngine.FLOWS,
    "expediente": GraphEngine.NOC152,
    "noc152": GraphEngine.NOC152,
}


def parse_engine(raw: str | None) -> GraphEngine:
    """Map UI projection id or legacy engine name → backend enum."""
    if not raw:
        return GraphEngine.COMBINED
    key = raw.strip().lower()
    if key in _ALIASES:
        return _ALIASES[key]
    for engine in GraphEngine:
        if engine.value == key:
            return engine
    return GraphEngine.COMBINED


def available_engines(workspace: Path) -> list[dict[str, Any]]:
    """Selector catalog = projection registry (id/label/description/status)."""
    return available_projections(workspace)


def build_graph(
    store: ExpedienteStore,
    *,
    service: Service | None,
    engine: GraphEngine,
    system: bool,
    workspace: Path | None = None,
) -> dict[str, Any]:
    ws = workspace or store.workspace

    if engine == GraphEngine.TECHNOLOGIES:
        return _annotate(build_technologies_graph(store), get_projection("technologies"))

    if engine == GraphEngine.FLOWS:
        return _annotate(build_flows_graph(store), get_projection("flows"))

    if engine in {GraphEngine.NETWORK, GraphEngine.OPENAPI}:
        return _annotate(build_network_projection(store, ws), get_projection("network"))

    if engine == GraphEngine.SERVICES:
        graph = build_services_projection(
            store, workspace=ws, service=service, system=system or service is None
        )
        return _annotate(graph, get_projection("services"))

    if engine == GraphEngine.ARCHIFY:
        # Whole-repo architecture (IR or logical fallback). Per-service keeps heuristic scene.
        if system or service is None:
            graph = build_architecture_projection(store, workspace=ws)
        else:
            graph = build_archify_scene(store, service)
        return _annotate(graph, get_projection("architecture"))

    if engine == GraphEngine.COMBINED:
        if system or service is None:
            graph = build_noc_combined_system(store, workspace=ws)
        else:
            graph = build_noc_combined_service(store, service, workspace=ws)
        return _annotate(graph, get_projection("general"))

    if engine == GraphEngine.NOC152:
        if system or service is None:
            graph = build_system_graph(store)
        else:
            graph = build_scene_graph(store, service)
        return _annotate(graph, get_projection("expediente"))

    raise ValueError(f"engine no soportado: {engine}")
