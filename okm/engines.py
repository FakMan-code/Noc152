"""Select which knowledge graph to project into the 3D viewer."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Never

from okm.archify_adapter import archify_to_graph, find_archify_spec, load_archify_spec
from okm.archify_graph import build_archify_scene, build_archify_system
from okm.layout3d import build_scene_graph, build_system_graph
from okm.models import Service
from okm.noc_combined import build_noc_combined_service, build_noc_combined_system
from okm.openapi_graph import find_openapi_spec, load_openapi_spec, openapi_to_graph
from okm.store import ExpedienteStore


class GraphEngine(str, Enum):
    ARCHIFY = "archify"
    COMBINED = "combined"
    NOC152 = "noc152"
    OPENAPI = "openapi"


def parse_engine(raw: str | None) -> GraphEngine:
    if not raw:
        return GraphEngine.COMBINED
    key = raw.strip().lower()
    for engine in GraphEngine:
        if engine.value == key:
            return engine
    return GraphEngine.COMBINED


def available_engines(workspace: Path) -> list[dict[str, str]]:
    """Engines shown in the UI selector. Combinado primero = arranque por defecto."""
    engines = [
        {"id": GraphEngine.COMBINED.value, "label": "Combinado NOC"},
        {"id": GraphEngine.ARCHIFY.value, "label": "Archify"},
        {"id": GraphEngine.NOC152.value, "label": "Noc152"},
    ]
    if find_openapi_spec(workspace) is not None:
        engines.append({"id": GraphEngine.OPENAPI.value, "label": "OpenAPI"})
    return engines


def build_graph(
    store: ExpedienteStore,
    *,
    service: Service | None,
    engine: GraphEngine,
    system: bool,
    workspace: Path | None = None,
) -> dict[str, Any]:
    ws = workspace or store.workspace

    if engine == GraphEngine.OPENAPI:
        spec_path = find_openapi_spec(ws)
        if spec_path is None:
            raise ValueError("no hay spec OpenAPI (workspace/openapi/ o docs/openapi/)")
        rel = None
        try:
            rel = str(spec_path.relative_to(ws))
        except ValueError:
            rel = str(spec_path)
        return openapi_to_graph(
            load_openapi_spec(spec_path),
            engine=engine.value,
            source=rel,
        )

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
                return build_noc_combined_system(store, workspace=ws)
            case _:
                unused: Never = engine
                raise ValueError(f"engine no soportado: {unused}")

    if service is None:
        raise ValueError("service requerido fuera de vista sistema")
    match engine:
        case GraphEngine.NOC152:
            return build_scene_graph(store, service)
        case GraphEngine.COMBINED:
            return build_noc_combined_service(store, service, workspace=ws)
        case _:
            unused: Never = engine
            raise ValueError(f"engine no soportado: {unused}")
