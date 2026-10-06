"""Select which knowledge graph to project into the 3D viewer."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Never

from okm.archify_adapter import archify_to_graph, find_archify_spec, load_archify_spec
from okm.archify_graph import build_archify_scene, build_archify_system, build_combined_scene
from okm.layout3d import build_scene_graph, build_system_graph
from okm.models import Service
from okm.store import ExpedienteStore


class GraphEngine(str, Enum):
    ARCHIFY = "archify"
    COMBINED = "combined"
    NOC152 = "noc152"


def parse_engine(raw: str | None) -> GraphEngine:
    if not raw:
        return GraphEngine.ARCHIFY
    key = raw.strip().lower()
    for engine in GraphEngine:
        if engine.value == key:
            return engine
    return GraphEngine.ARCHIFY


def build_graph(
    store: ExpedienteStore,
    *,
    service: Service | None,
    engine: GraphEngine,
    system: bool,
    workspace: Path | None = None,
) -> dict[str, Any]:
    ws = workspace or store.workspace
    # Preferred path: official Archify IR JSON → 3D (motor Archify intacto).
    if engine == GraphEngine.ARCHIFY:
        spec_path = find_archify_spec(ws)
        if spec_path is not None:
            return archify_to_graph(load_archify_spec(spec_path), engine=engine.value)
        # Fallback: heuristic IR from expediente (legacy helper).
        if system:
            return build_archify_system(store)
        if service is None:
            raise ValueError("service requerido fuera de vista sistema")
        return build_archify_scene(store, service)

    if system:
        match engine:
            case GraphEngine.NOC152:
                return build_system_graph(store)
            case GraphEngine.COMBINED:
                graph = build_archify_system(store)
                graph["engine"] = GraphEngine.COMBINED.value
                return graph
            case _:
                unused: Never = engine
                raise ValueError(f"engine no soportado: {unused}")

    if service is None:
        raise ValueError("service requerido fuera de vista sistema")
    match engine:
        case GraphEngine.NOC152:
            return build_scene_graph(store, service)
        case GraphEngine.COMBINED:
            return build_combined_scene(store, service)
        case _:
            unused: Never = engine
            raise ValueError(f"engine no soportado: {unused}")
