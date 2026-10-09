"""Graph projections: one ingest, many views over the same expediente.

User-facing catalog. Each projection builds a 3D graph payload without re-ingest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from okm.health import health_legend, status_color, status_label
from okm.humanize import is_noise_service, source_display_name
from okm.layout3d import apply_positions
from okm.models import EpistemicKind
from okm.noc_combined import (
    _KNOWN_DEPS,
    _PRODUCT_STORY,
    _SELF_ROLES,
    _story,
    build_noc_combined_service,
    build_noc_combined_system,
    is_self_map_workspace,
    self_map_part_count,
)
from okm.store import ExpedienteStore

ProjectionStatus = Literal["ready", "partial", "stub"]

_SKIP_PACKAGES = {
    "os",
    "sys",
    "re",
    "json",
    "logging",
    "typing",
    "pathlib",
    "datetime",
    "collections",
    "concurrent",
    "random",
    "time",
    "uuid",
    "copy",
    "functools",
    "itertools",
    "subprocess",
    "threading",
    "asyncio",
    "http",
    "urllib",
    "setuptools",
    "pip",
    "wheel",
    "pkg_resources",
    "google",
    "dotenv",
    "python-dotenv",
    "pytest",
    "nodemon",
    "prettytable",
    "dotmap",
    "okm",
    "argparse",
    "dataclasses",
    "enum",
    "hashlib",
    "mimetypes",
    "shutil",
    "tomllib",
    "traceback",
}

_TECH_ALIASES: dict[str, str] = {
    "flask": "Flask",
    "flask-cors": "Flask",
    "grpcio": "gRPC",
    "grpcio-tools": "gRPC",
    "grpc": "gRPC",
    "pymongo": "MongoDB",
    "react": "React",
    "react-dom": "React",
    "express": "Express",
    "fastapi": "FastAPI",
    "django": "Django",
    "requests": "HTTP client",
    "axios": "HTTP client",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "nodejs": "Node.js",
    "node": "Node.js",
    "numpy": "NumPy",
    "sqlite3": "SQLite",
    "three": "Three.js",
    "three.js": "Three.js",
    "ollama": "Ollama",
}

# Stack known for the Noc152 mono-repo (when claims are thin / noise-filtered)
_SELF_STACK: list[tuple[str, list[str]]] = [
    ("Python", ["role:ingest", "role:expediente", "role:combinado", "role:serve"]),
    ("SQLite", ["role:expediente"]),
    ("Three.js", ["role:serve"]),
    ("OpenAPI", ["role:openapi"]),
    ("Archify IR", ["role:archify"]),
    ("Ollama", ["role:asistente"]),
]


@dataclass(frozen=True)
class GraphProjection:
    id: str
    label: str
    description: str
    questions: tuple[str, ...]
    status: ProjectionStatus
    # Underlying build key (may equal id)
    engine: str


# Catalog order = UI order
PROJECTIONS: tuple[GraphProjection, ...] = (
    GraphProjection(
        id="general",
        label="General",
        description="Historia del producto: roles humanos y quién depende de quién.",
        questions=("¿Qué es esta app?", "¿Qué piezas la componen?"),
        status="ready",
        engine="combined",
    ),
    GraphProjection(
        id="services",
        label="Servicios",
        description="Servicios detectados y dependencias (impacto si uno falla).",
        questions=("¿Qué servicios hay?", "¿Qué consume cada uno?", "¿Cuál es crítico?"),
        status="ready",
        engine="services",
    ),
    GraphProjection(
        id="architecture",
        label="Arquitectura",
        description="Capas/componentes (Archify IR si existe; si no, vista parcial).",
        questions=("¿Cómo está partido el sistema?", "¿Qué boundaries hay?"),
        status="partial",
        engine="archify",
    ),
    GraphProjection(
        id="technologies",
        label="Herramientas",
        description="Stack detectado en el expediente (paquetes, runtimes, contenedores).",
        questions=("¿Con qué está hecho?", "¿Qué libs comparte más de un servicio?"),
        status="ready",
        engine="technologies",
    ),
    GraphProjection(
        id="network",
        label="Red",
        description="Contrato HTTP / integraciones (OpenAPI). Sin secretos.",
        questions=("¿Qué endpoints hay?", "¿Cómo se llama la API?"),
        status="partial",
        engine="network",
    ),
    GraphProjection(
        id="flows",
        label="Flujos",
        description="Camino de una acción por el sistema (cuando hay deps conocidas).",
        questions=("¿Cómo llega un request al core?", "¿Qué pasos hay en el flujo?"),
        status="partial",
        engine="flows",
    ),
    GraphProjection(
        id="expediente",
        label="Expediente",
        description="Claims, evidencia y gaps del scan (vista densa).",
        questions=("¿Qué vimos en el repo?", "¿Dónde hay huecos?"),
        status="ready",
        engine="noc152",
    ),
)


_BY_ID = {p.id: p for p in PROJECTIONS}
_ENGINE_ALIASES: dict[str, str] = {
    "general": "combined",
    "combined": "combined",
    "combinado": "combined",
    "services": "services",
    "servicios": "services",
    "architecture": "archify",
    "archify": "archify",
    "arquitectura": "archify",
    "technologies": "technologies",
    "tools": "technologies",
    "herramientas": "technologies",
    "network": "network",
    "red": "network",
    "openapi": "network",
    "flows": "flows",
    "flujos": "flows",
    "expediente": "noc152",
    "noc152": "noc152",
}


def resolve_projection_id(raw: str | None) -> str:
    if not raw:
        return "general"
    key = raw.strip().lower()
    if key in _BY_ID:
        return key
    engine = _ENGINE_ALIASES.get(key)
    if engine:
        for p in PROJECTIONS:
            if p.engine == engine or p.id == engine:
                return p.id
    return "general"


def get_projection(projection_id: str | None) -> GraphProjection:
    pid = resolve_projection_id(projection_id)
    return _BY_ID.get(pid, PROJECTIONS[0])


def available_projections(workspace: Path) -> list[dict[str, Any]]:
    """UI catalog — built from the registry (no hard-coded select options)."""
    from okm.archify_adapter import find_archify_spec
    from okm.openapi_graph import find_openapi_spec

    out: list[dict[str, Any]] = []
    for p in PROJECTIONS:
        status = p.status
        if p.id == "architecture" and find_archify_spec(workspace) is None:
            status = "partial"
        if p.id == "network" and find_openapi_spec(workspace) is None:
            status = "stub"
        out.append(
            {
                "id": p.id,
                "label": p.label,
                "description": p.description,
                "questions": list(p.questions),
                "status": status,
                "engine": p.engine,
            }
        )
    return out


def _annotate(graph: dict[str, Any], projection: GraphProjection) -> dict[str, Any]:
    graph = dict(graph)
    graph["projection"] = {
        "id": projection.id,
        "label": projection.label,
        "description": projection.description,
        "questions": list(projection.questions),
        "status": projection.status,
    }
    graph["engine"] = projection.engine
    intro = dict(graph.get("intro") or {})
    if not intro.get("what_is_it"):
        intro["what_is_it"] = projection.description
    intro.setdefault("projection", projection.label)
    graph["intro"] = intro
    return graph


def _is_self(store: ExpedienteStore, workspace: Path | None = None) -> bool:
    run = store.latest_run() or {}
    visible = [s for s in store.list_services() if not is_noise_service(s.name)]
    title = source_display_name(run.get("source_uri"))
    return is_self_map_workspace(
        run.get("source_uri"), title, visible, workspace=workspace or store.workspace
    )


def build_services_projection(
    store: ExpedienteStore, *, workspace: Path | None = None, service=None, system: bool = True
) -> dict[str, Any]:
    """Same nodes as Combinado; framing focused on blast radius / deps."""
    ws = workspace or store.workspace
    if system or service is None:
        graph = build_noc_combined_system(store, workspace=ws)
    else:
        graph = build_noc_combined_service(store, service, workspace=ws)
    intro = dict(graph.get("intro") or {})
    intro["title"] = intro.get("title") or source_display_name(
        (store.latest_run() or {}).get("source_uri")
    )
    if _is_self(store, ws):
        intro["body"] = (
            f"Partes de Noc152 ({self_map_part_count()} capas lógicas). "
            "No son microservicios: son piezas del propio producto (Ingest → Briefing)."
        )
    else:
        intro["body"] = (
            "Grafo de servicios: cada nodo es una pieza desplegable. "
            "Las flechas son dependencias — si corta un nodo, mirá quién lo usa."
        )
    intro["what_is_it"] = intro["body"]
    graph["intro"] = intro
    return graph


def build_architecture_projection(
    store: ExpedienteStore, *, workspace: Path | None = None
) -> dict[str, Any]:
    """Archify IR when present; otherwise Combinado layers (honest partial)."""
    from okm.archify_adapter import archify_to_graph, find_archify_spec, load_archify_spec
    from okm.archify_graph import build_archify_system

    ws = workspace or store.workspace
    spec = find_archify_spec(ws)
    if spec is not None:
        graph = archify_to_graph(load_archify_spec(spec), engine="archify")
        intro = dict(graph.get("intro") or {})
        intro["body"] = (
            "Arquitectura desde IR Archify (curado). Capas y boundaries del documento."
        )
        intro["what_is_it"] = intro["body"]
        graph["intro"] = intro
        return graph

    visible = [s for s in store.list_services() if not is_noise_service(s.name)]
    if _is_self(store, ws) or not visible:
        graph = build_noc_combined_system(store, workspace=ws)
        intro = dict(graph.get("intro") or {})
        intro["title"] = intro.get("title") or "Noc152"
        intro["body"] = (
            "Arquitectura lógica de Noc152 (sin IR Archify en esta raíz): "
            "capas Ingest → Expediente → motores → Briefing. "
            "Marcado como partial — no inventamos un architecture.json."
        )
        intro["what_is_it"] = intro["body"]
        graph["intro"] = intro
        graph["view"] = "architecture-logical"
        return graph

    graph = build_archify_system(store)
    intro = dict(graph.get("intro") or {})
    intro["body"] = (
        "Arquitectura heurística desde servicios del expediente "
        "(no hay architecture.json). Partial."
    )
    intro["what_is_it"] = intro["body"]
    graph["intro"] = intro
    return graph


def _normalize_tech(raw: str) -> str | None:
    name = raw.strip()
    name = re.sub(r"^Declares (Python requirement|npm dependency):\s*", "", name, flags=re.I)
    name = re.sub(r"^Python import:\s*", "", name, flags=re.I)
    name = re.sub(r"^container base image:\s*", "", name, flags=re.I)
    name = name.split("==")[0].split(">=")[0].split("~=")[0].split("@")[0].strip()
    name = name.strip("'\"")
    if not name or len(name) < 2:
        return None
    key = name.lower().replace("_", "-")
    if key in _SKIP_PACKAGES or key.startswith("_"):
        return None
    if key in _TECH_ALIASES:
        return _TECH_ALIASES[key]
    # Drop deep relative imports
    if "." in name and not name.startswith("@"):
        head = name.split(".")[0].lower()
        if head in _SKIP_PACKAGES:
            return None
    return name[0].upper() + name[1:] if name.islower() else name


def build_technologies_graph(store: ExpedienteStore) -> dict[str, Any]:
    """Hub = stack; leaves = services that declare each tech (from claims)."""
    run = store.latest_run() or {}
    source_uri = run.get("source_uri")
    title = source_display_name(source_uri)
    visible = [s for s in store.list_services() if not is_noise_service(s.name)]
    self_map = _is_self(store)
    # Self-map: Noc152 service is noise but holds the only claims — include it.
    services = visible if visible else list(store.list_services())
    if self_map and not visible:
        services = list(store.list_services())

    # tech_label -> set(service_name)
    uses: dict[str, set[str]] = {}
    evidence_note: dict[str, str] = {}

    for svc in services:
        for claim in store.claims_for(svc.service_id):
            if claim.kind == EpistemicKind.GAP:
                continue
            pred = (claim.predicate or "").lower()
            if pred not in {
                "depends_on_package",
                "imports_module",
                "container_base_image",
                "package_name",
            }:
                continue
            tech = _normalize_tech(claim.object_value or claim.statement or "")
            if not tech:
                continue
            owner = "Noc152" if self_map else svc.name
            uses.setdefault(tech, set()).add(owner)
            if tech not in evidence_note and claim.evidence_ids:
                evidence_note[tech] = claim.evidence_ids[0]

    if self_map:
        for tech, role_ids in _SELF_STACK:
            uses.setdefault(tech, set()).add("Noc152")
            # tie tech to logical roles for edges later
            for rid in role_ids:
                uses[tech].add(rid)

    # Keep techs used by ≥1 service; prefer shared (≥2) first, cap size
    ranked = sorted(uses.items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))
    ranked = ranked[:18]

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    details: dict[str, dict[str, Any]] = {}

    hub_id = "tech:hub"
    nodes.append(
        {
            "id": hub_id,
            "kind": "product",
            "label": "Stack",
            "layer": 0,
            "color": status_color("principal"),
            "size": 1.45,
            "facet": "product",
            "health": "principal",
            "health_label": status_label("principal"),
            "role": "Stack",
        }
    )
    details[hub_id] = {
        "title": f"Herramientas · {title}",
        "kind": "product",
        "kind_label": "stack",
        "subtitle": "detectado en el expediente",
        "summary": (
            f"{len(ranked)} tecnologías agrupadas desde manifests/imports. "
            "No se lista cada paquete npm/pypi."
        ),
        "meta": {"servicios": len(services), "tecnologías": len(ranked)},
        "sections": [],
        "facet": "product",
    }

    # Consumers: microservices or self-map logical roles
    svc_ids: dict[str, str] = {}
    if self_map:
        for role in _SELF_ROLES:
            rid = str(role["id"])
            svc_ids[rid] = rid
            svc_ids[str(role["role"])] = rid
            nodes.append(
                {
                    "id": rid,
                    "kind": "service",
                    "label": str(role["role"])[:26],
                    "layer": 2,
                    "color": status_color("neutral"),
                    "size": 0.95,
                    "facet": "service",
                    "service_name": rid,
                    "health": "neutral",
                    "health_label": status_label("neutral"),
                    "role": str(role["role"]),
                }
            )
            details[rid] = {
                "title": str(role["role"]),
                "kind": "service",
                "kind_label": "capa",
                "subtitle": "pieza de Noc152",
                "summary": str(role["blurb"]),
                "meta": {"tipo": "capa lógica"},
                "sections": [],
                "facet": "service",
            }
        svc_ids["Noc152"] = hub_id
    else:
        for svc in services:
            sid = f"svc:{svc.service_id}"
            svc_ids[svc.name] = sid
            role = _story(svc.name)["role"]
            nodes.append(
                {
                    "id": sid,
                    "kind": "service",
                    "label": role[:26],
                    "layer": 2,
                    "color": status_color("neutral"),
                    "size": 0.95,
                    "facet": "service",
                    "service_name": svc.name,
                    "health": "neutral",
                    "health_label": status_label("neutral"),
                    "role": role,
                }
            )
            details[sid] = {
                "title": role,
                "kind": "service",
                "kind_label": "servicio",
                "subtitle": svc.name,
                "summary": _story(svc.name)["blurb"],
                "meta": {"servicio": svc.name},
                "sections": [],
                "facet": "service",
                "open_service": svc.name,
            }

    for tech, owners in ranked:
        tid = f"tech:{re.sub(r'[^a-zA-Z0-9]+', '-', tech.lower()).strip('-')}"
        # owners may mix service names and role ids
        real_owners = [o for o in owners if o != "Noc152" or not self_map]
        if self_map:
            real_owners = [o for o in owners if o.startswith("role:") or o in svc_ids]
        shared = len(set(real_owners)) >= 2
        nodes.append(
            {
                "id": tid,
                "kind": "module",
                "label": tech[:22],
                "layer": 1,
                "color": status_color("ok") if shared else status_color("neutral"),
                "size": 1.15 if shared else 1.0,
                "facet": "runtime",
                "health": "ok" if shared else "neutral",
                "health_label": "compartida" if shared else "local",
                "role": tech,
            }
        )
        edges.append(
            {
                "id": f"{hub_id}->{tid}",
                "source": hub_id,
                "target": tid,
                "kind": "contains",
                "label": "",
                "color": "#3a3a3a",
            }
        )
        owner_labels = sorted(
            {
                (details.get(svc_ids[o], {}) or {}).get("title") or o
                for o in owners
                if o in svc_ids or o == "Noc152"
            }
        )
        details[tid] = {
            "title": tech,
            "kind": "module",
            "kind_label": "tecnología",
            "subtitle": f"{len(owner_labels) or 1} uso(s)",
            "summary": (
                f"Detectada en el expediente / stack conocido. "
                f"Usada por: {', '.join(owner_labels) or 'Noc152'}."
            ),
            "meta": {
                "confianza": "observed" if tech not in {t for t, _ in _SELF_STACK} else "derived",
                "usos": len(owner_labels),
            },
            "sections": [
                {
                    "title": "Quién la usa",
                    "items": [
                        {"statement": n, "kind": "observed"} for n in owner_labels
                    ],
                }
            ],
            "facet": "runtime",
            "sources": [],
        }
        for owner in owners:
            sid = svc_ids.get(owner)
            if not sid or sid == hub_id:
                continue
            edges.append(
                {
                    "id": f"{sid}->uses->{tid}",
                    "source": sid,
                    "target": tid,
                    "kind": "depends",
                    "label": "usa",
                    "color": "#64748b",
                }
            )

    apply_positions(nodes, edges)
    return {
        "engine": "technologies",
        "title": f"Herramientas · {title}",
        "service": None,
        "system": True,
        "nodes": nodes,
        "edges": edges,
        "details": details,
        "facets": [
            {"id": "product", "label": "stack"},
            {"id": "runtime", "label": "tecnología"},
            {"id": "service", "label": "servicio"},
        ],
        "legend": health_legend(),
        "intro": {
            "title": f"Herramientas · {title}",
            "body": (
                "Stack agrupado desde claims del expediente (package.json, requirements, imports). "
                "Verde = tecnología compartida por ≥2 servicios."
            ),
            "what_is_it": "Grafo de herramientas y tecnologías del repo.",
            "node_legend": [],
        },
    }


def build_flows_graph(store: ExpedienteStore) -> dict[str, Any]:
    """Linear-ish product flow from known deps / product story — not invented calls."""
    run = store.latest_run() or {}
    source_uri = (run.get("source_uri") or "").lower().replace("\\", "/")
    title = source_display_name(run.get("source_uri"))
    services = {
        s.name.lower(): s
        for s in store.list_services()
        if not is_noise_service(s.name)
    }

    # Self-map: ingest → expediente → combinado → briefing
    if _is_self(store):
        chain_roles = [
            r for r in _SELF_ROLES if r["id"] in {
                "role:ingest",
                "role:expediente",
                "role:combinado",
                "role:serve",
            }
        ]
        # preserve order of _SELF_ROLES
        chain_roles = [r for r in _SELF_ROLES if r["id"] in {x["id"] for x in chain_roles}]
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        details: dict[str, dict[str, Any]] = {}
        prev = None
        for i, role in enumerate(chain_roles):
            nid = f"flow:{role['id']}"
            label = str(role["role"])
            nodes.append(
                {
                    "id": nid,
                    "kind": "service",
                    "label": f"{i + 1}. {label}"[:26],
                    "layer": i,
                    "color": status_color("principal") if i == 0 else status_color("neutral"),
                    "size": 1.2 if i == 0 else 1.05,
                    "facet": "service",
                    "service_name": str(role["id"]),
                    "health": "principal" if i == 0 else "neutral",
                    "health_label": status_label("principal" if i == 0 else "neutral"),
                    "role": label,
                }
            )
            details[nid] = {
                "title": label,
                "kind": "service",
                "kind_label": f"paso {i + 1}",
                "subtitle": "capa Noc152",
                "summary": str(role["blurb"]),
                "meta": {"paso": i + 1, "confianza": "derived"},
                "sections": [],
                "facet": "service",
            }
            if prev:
                edges.append(
                    {
                        "id": f"{prev}->{nid}",
                        "source": prev,
                        "target": nid,
                        "kind": "calls",
                        "label": "luego",
                        "color": "#38bdf8",
                    }
                )
            prev = nid
        apply_positions(nodes, edges, seed=252)
        flow_txt = " → ".join(str(r["role"]) for r in chain_roles)
        return {
            "engine": "flows",
            "title": f"Flujo · {title}",
            "service": None,
            "system": True,
            "nodes": nodes,
            "edges": edges,
            "details": details,
            "facets": [{"id": "service", "label": "paso"}],
            "legend": health_legend(),
            "intro": {
                "title": f"Flujo · {title}",
                "body": (
                    f"Pipeline del propio Noc152 (derived): {flow_txt}. "
                    "Así se entiende un repo: ingestás, guardás, proyectás, mostrás."
                ),
                "what_is_it": flow_txt,
                "node_legend": [],
            },
        }

    story = None
    for key, st in _PRODUCT_STORY.items():
        if key in source_uri or key.replace("-", "") in source_uri.replace("-", ""):
            story = st
            break
    if story is None and "martian" in source_uri:
        story = _PRODUCT_STORY.get("martian-bank-demo")
    if story is None and ("boutique" in source_uri or "microservices-demo" in source_uri):
        story = _PRODUCT_STORY.get("microservices-demo")

    chain: list[str] = []
    if "ui" in services:
        chain = ["ui", "customer-auth", "dashboard", "accounts"]
        chain = [c for c in chain if c in services]
    elif "frontend" in services:
        chain = ["frontend", "checkoutservice", "paymentservice"]
        chain = [c for c in chain if c in services]
    else:
        for src, targets in _KNOWN_DEPS.items():
            if src in services:
                chain = [src] + [t for t in targets if t in services][:3]
                break

    if len(chain) < 2:
        return _stub_graph(
            title=title,
            projection_label="Flujos",
            body=(
                "Aún no hay un flujo confiable detectado en este repo "
                "(faltan deps conocidas entre servicios). "
                "Usá Servicios o General; los flujos se completan con más extractores."
            ),
        )

    nodes = []
    edges = []
    details = {}
    prev = None
    for i, name in enumerate(chain):
        svc = services[name]
        role = _story(name)["role"]
        nid = f"flow:{name}"
        nodes.append(
            {
                "id": nid,
                "kind": "service",
                "label": f"{i + 1}. {role}"[:26],
                "layer": i,
                "color": status_color("principal") if i == 0 else status_color("neutral"),
                "size": 1.2 if i == 0 else 1.05,
                "facet": "service",
                "service_name": svc.name,
                "health": "principal" if i == 0 else "neutral",
                "health_label": status_label("principal" if i == 0 else "neutral"),
                "role": role,
            }
        )
        details[nid] = {
            "title": role,
            "kind": "service",
            "kind_label": f"paso {i + 1}",
            "subtitle": svc.name,
            "summary": _story(name)["blurb"],
            "meta": {
                "paso": i + 1,
                "confianza": "derived",
                "nota": "Cadena desde deps conocidas del producto, no call-graph completo.",
            },
            "sections": [],
            "facet": "service",
            "open_service": svc.name,
        }
        if prev:
            edges.append(
                {
                    "id": f"{prev}->{nid}",
                    "source": prev,
                    "target": nid,
                    "kind": "calls",
                    "label": "luego",
                    "color": "#38bdf8",
                }
            )
        prev = nid

    apply_positions(nodes, edges, seed=252)
    flow_txt = (story or {}).get("flow") or " → ".join(
        _story(n)["role"] for n in chain
    )
    return {
        "engine": "flows",
        "title": f"Flujo · {title}",
        "service": None,
        "system": True,
        "nodes": nodes,
        "edges": edges,
        "details": details,
        "facets": [{"id": "service", "label": "paso"}],
        "legend": health_legend(),
        "intro": {
            "title": f"Flujo · {title}",
            "body": (
                f"Camino derivado (derived) del producto: {flow_txt}. "
                "No es un call-graph exhaustivo — solo pasos con deps conocidas."
            ),
            "what_is_it": flow_txt,
            "node_legend": [],
        },
    }


def _stub_graph(*, title: str, projection_label: str, body: str) -> dict[str, Any]:
    hub = "stub:hub"
    nodes = [
        {
            "id": hub,
            "kind": "product",
            "label": projection_label[:22],
            "layer": 0,
            "color": status_color("alert"),
            "size": 1.4,
            "facet": "product",
            "health": "alert",
            "health_label": "parcial",
            "role": projection_label,
        }
    ]
    details = {
        hub: {
            "title": projection_label,
            "kind": "product",
            "kind_label": "vista parcial",
            "subtitle": title,
            "summary": body,
            "meta": {"estado": "stub"},
            "sections": [
                {
                    "title": "Por qué está vacía",
                    "items": [{"statement": body, "kind": "gap"}],
                }
            ],
            "facet": "product",
        }
    }
    apply_positions(nodes, [])
    return {
        "engine": "stub",
        "title": f"{projection_label} · {title}",
        "service": None,
        "system": True,
        "nodes": nodes,
        "edges": [],
        "details": details,
        "facets": [],
        "legend": health_legend(),
        "intro": {
            "title": f"{projection_label} · {title}",
            "body": body,
            "what_is_it": body,
            "node_legend": [],
        },
    }


def build_network_projection(store: ExpedienteStore, workspace: Path) -> dict[str, Any]:
    from okm.openapi_graph import find_openapi_spec, load_openapi_spec, openapi_to_graph

    spec = find_openapi_spec(workspace)
    if spec is None:
        title = source_display_name((store.latest_run() or {}).get("source_uri"))
        return _stub_graph(
            title=title,
            projection_label="Red",
            body=(
                "No hay OpenAPI en esta raíz. "
                "Agregá workspace/openapi/*.openapi.json o usá otra proyección."
            ),
        )
    rel = str(spec)
    try:
        rel = str(spec.relative_to(workspace))
    except ValueError:
        pass
    graph = openapi_to_graph(load_openapi_spec(spec), engine="network", source=rel)
    intro = dict(graph.get("intro") or {})
    intro["body"] = (
        "Grafo de red / contrato HTTP (OpenAPI). "
        "Muestra tags, operations y schemas — borde del sistema, no el cerebro NOC."
    )
    intro["what_is_it"] = intro["body"]
    graph["intro"] = intro
    return graph
