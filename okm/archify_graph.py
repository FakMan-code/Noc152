"""Archify-style knowledge IR projected into the Noc152 3D graph format.

Archify does not extract operational claims. It authors a typed architecture:
components, labeled connections, boundaries, and source spans. This module
rebuilds that IR from the expediente (modules + manifests) and from evidence
blobs, then maps it onto the same Three.js payload as Noc152.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from okm.health import NODE_COLOR, service_health
from okm.humanize import (
    facet_filter_label,
    human_claim,
    is_noise_service,
    kind_label,
    source_display_name,
)
from okm.layout3d import apply_positions
from okm.models import Claim, EpistemicKind, Facet, Service
from okm.store import ExpedienteStore

_FROM_LOCAL = re.compile(
    r"^\s*from\s+(?P<pkg>[A-Za-z0-9_]+)\.(?P<mod>[A-Za-z0-9_]+)\s+import\b"
)
_IMPORT_TOP = re.compile(r"^\s*(?:from|import)\s+(?P<mod>[A-Za-z0-9_]+)\b")

_STDLIB = frozenset(
    {
        "abc",
        "argparse",
        "asyncio",
        "base64",
        "collections",
        "concurrent",
        "contextlib",
        "copy",
        "csv",
        "dataclasses",
        "datetime",
        "enum",
        "functools",
        "getpass",
        "glob",
        "gzip",
        "hashlib",
        "html",
        "http",
        "importlib",
        "inspect",
        "io",
        "itertools",
        "json",
        "logging",
        "math",
        "mimetypes",
        "multiprocessing",
        "os",
        "pathlib",
        "pkgutil",
        "platform",
        "pprint",
        "re",
        "secrets",
        "shutil",
        "socket",
        "sqlite3",
        "ssl",
        "string",
        "struct",
        "subprocess",
        "sys",
        "tempfile",
        "textwrap",
        "threading",
        "traceback",
        "types",
        "typing",
        "typing_extensions",
        "unittest",
        "urllib",
        "uuid",
        "warnings",
        "weakref",
        "xml",
        "zipfile",
        "__future__",
    }
)

_SKIP_MODS = frozenset({"__init__", "__main__", "config"})

ARCHIFY_COLOR = {
    "frontend": "#c4b5fd",
    "backend": "#34d399",
    "database": "#60a5fa",
    "cloud": "#818cf8",
    "security": "#fb7185",
    "messagebus": "#fbbf24",
    "external": "#38bdf8",
    "hub": NODE_COLOR["hub"],
}

# Prefer pipeline-shaped modules when a package has many files (Archify: ≤12 nodes).
_PIPELINE_HINTS = (
    "ingest",
    "extract",
    "resolve",
    "store",
    "pipeline",
    "layout3d",
    "serve",
    "ask",
    "agent",
    "cli",
    "health",
    "humanize",
)


def _clip(text: str, n: int = 22) -> str:
    text = text.strip()
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def _py_files(store: ExpedienteStore, service: Service) -> dict[str, str]:
    """path → blob_sha for Python files under the service root."""
    out: dict[str, str] = {}
    root = (service.root_path or ".").replace("\\", "/").strip("/")
    for ev in store.list_evidence():
        path = ev.path.replace("\\", "/")
        if not path.endswith(".py"):
            continue
        if any(part.startswith(".") for part in Path(path).parts):
            continue
        if root not in {"", "."}:
            prefix = root if root.endswith("/") else root + "/"
            if path != root and not path.startswith(prefix):
                continue
        out[path] = ev.blob_sha
    return out


def _local_package(paths: list[str]) -> str | None:
    counts: dict[str, int] = {}
    for path in paths:
        parts = Path(path).parts
        if len(parts) >= 2 and parts[0] not in {".", "tests", "docs"}:
            counts[parts[0]] = counts.get(parts[0], 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def _module_stem(path: str) -> str:
    return Path(path).stem


def _parse_imports(text: str, pkg: str | None) -> tuple[set[str], set[str]]:
    local: set[str] = set()
    external: set[str] = set()
    for line in text.splitlines():
        m = _FROM_LOCAL.match(line)
        if m and pkg and m.group("pkg") == pkg:
            local.add(m.group("mod"))
            continue
        top = _IMPORT_TOP.match(line)
        if not top:
            continue
        name = top.group("mod")
        if name in _STDLIB or name.startswith("_"):
            continue
        if pkg and name == pkg:
            continue
        external.add(name)
    return local, external


def _pick_modules(stems: list[str]) -> list[str]:
    hinted = [s for s in _PIPELINE_HINTS if s in stems]
    if hinted:
        return hinted[:12]
    return stems[:12]


def _node(
    *,
    nid: str,
    label: str,
    kind: str,
    color: str,
    layer: int,
    size: float,
    facet: str | None,
    archify_type: str,
) -> dict[str, Any]:
    return {
        "id": nid,
        "kind": kind,
        "label": _clip(label),
        "layer": layer,
        "color": color,
        "size": size,
        "facet": facet,
        "archify_type": archify_type,
    }


def _detail(
    *,
    title: str,
    kind: str,
    subtitle: str,
    summary: str,
    facet: str | None,
    sections: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
    open_service: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": title,
        "kind": kind,
        "kind_label": kind_label(kind) if kind in {"observed", "inferred", "gap"} else kind,
        "subtitle": subtitle,
        "summary": summary,
        "meta": meta or {},
        "sections": sections or [],
        "facet": facet,
    }
    if open_service:
        payload["open_service"] = open_service
    return payload


def _identity_summary(claims: list[Claim]) -> str:
    for pred in ("likely_purpose", "documented_title", "package_name"):
        for claim in claims:
            if claim.predicate == pred and claim.object_value:
                return human_claim(claim)
    return ""


def _archify_model(store: ExpedienteStore, service: Service) -> dict[str, Any]:
    claims = store.claims_for(service.service_id)
    relations = store.relations_for(service.service_id)
    health = service_health(store, service)
    py_files = _py_files(store, service)
    pkg = _local_package(list(py_files))

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    details: dict[str, dict[str, Any]] = {}

    hub_id = f"svc:{service.service_id}"
    nodes.append(
        _node(
            nid=hub_id,
            label=service.name,
            kind="service",
            color=health["color"] if health["health"] != "ok" else ARCHIFY_COLOR["hub"],
            layer=0,
            size=1.35,
            facet=None,
            archify_type="backend",
        )
    )
    details[hub_id] = _detail(
        title=service.name,
        kind="service",
        subtitle="componente · backend",
        summary=_identity_summary(claims) or f"Servicio {service.name}.",
        facet="identity",
        meta={"tipo": "backend", "salud": health["label"]},
    )

    module_paths = {
        _module_stem(path): path
        for path in py_files
        if _module_stem(path) not in _SKIP_MODS
    }
    chosen = _pick_modules(sorted(module_paths))
    chosen_set = set(chosen)

    import_map: dict[str, tuple[set[str], set[str]]] = {}
    for stem in chosen:
        path = module_paths[stem]
        sha = py_files[path]
        try:
            text = store.get_blob(sha).decode("utf-8", errors="replace")
        except OSError:
            text = ""
        import_map[stem] = _parse_imports(text, pkg)

    for stem in chosen:
        nid = f"mod:{stem}"
        nodes.append(
            _node(
                nid=nid,
                label=stem,
                kind="facet",
                color=ARCHIFY_COLOR["backend"],
                layer=1,
                size=0.92,
                facet="runtime",
                archify_type="backend",
            )
        )
        path = module_paths[stem]
        details[nid] = _detail(
            title=stem,
            kind="backend",
            subtitle="módulo · Archify IR",
            summary=f"Componente de código `{path}` (IR tipo Archify: backend).",
            facet="runtime",
            meta={"archivo": path, "tipo": "backend"},
        )
        edges.append({"source": hub_id, "target": nid, "kind": "contains"})

    seen_mod_edges: set[tuple[str, str]] = set()
    for stem, (local, _ext) in import_map.items():
        for dest in local:
            if dest not in chosen_set or dest == stem:
                continue
            key = (stem, dest)
            if key in seen_mod_edges:
                continue
            seen_mod_edges.add(key)
            edges.append(
                {
                    "source": f"mod:{stem}",
                    "target": f"mod:{dest}",
                    "kind": "uses",
                    "label": "import",
                }
            )

    ext_counts: dict[str, int] = {}
    for _stem, (_local, ext) in import_map.items():
        for name in ext:
            ext_counts[name] = ext_counts.get(name, 0) + 1
    for rel in relations:
        if rel.kind == "depends_on_package":
            name = rel.to_ref.split(":", 1)[-1]
            ext_counts[name] = ext_counts.get(name, 0) + 2

    pip_deps: list[str] = []
    seen_dep: set[str] = set()
    for rel in relations:
        if rel.kind != "depends_on_package":
            continue
        name = rel.to_ref.split(":", 1)[-1]
        if name in _STDLIB or name in seen_dep:
            continue
        seen_dep.add(name)
        pip_deps.append(name)
    extra_ext = [
        name
        for name, _n in sorted(ext_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        if name not in seen_dep and name not in _STDLIB
    ]
    for name in (pip_deps + extra_ext)[:6]:
        did = f"dep:{name}"
        if any(n["id"] == did for n in nodes):
            continue
        nodes.append(
            _node(
                nid=did,
                label=name,
                kind="dependency",
                color=ARCHIFY_COLOR["external"],
                layer=2,
                size=0.78,
                facet="topology",
                archify_type="external",
            )
        )
        details[did] = _detail(
            title=name,
            kind="dependency",
            subtitle="external · Archify",
            summary=f"Dependencia externa `{name}`.",
            facet="topology",
            meta={"tipo": "external"},
        )
        edges.append({"source": hub_id, "target": did, "kind": "depends_on", "label": "depende"})

    runtime_claims = [c for c in claims if c.predicate in {"container_base_image", "exposes_port"}]
    for claim in runtime_claims[:4]:
        nid = f"rt:{claim.claim_id[:12]}"
        nodes.append(
            _node(
                nid=nid,
                label=_clip(claim.object_value or claim.predicate, 20),
                kind="claim",
                color=ARCHIFY_COLOR["cloud"],
                layer=2,
                size=0.72,
                facet="runtime",
                archify_type="cloud",
            )
        )
        details[nid] = _detail(
            title=claim.object_value or claim.predicate,
            kind="cloud",
            subtitle="runtime · Archify",
            summary=human_claim(claim),
            facet="runtime",
            meta={"tipo": "cloud", "predicado": claim.predicate},
        )
        edges.append({"source": hub_id, "target": nid, "kind": "runs_on", "label": "runtime"})

    return {
        "nodes": nodes,
        "edges": edges,
        "details": details,
        "health": health,
        "claims": claims,
        "hub_id": hub_id,
    }


def _attach_operational_gaps(model: dict[str, Any]) -> None:
    """Noc152 contribution: explicit gaps, with evidence language."""
    nodes: list[dict[str, Any]] = model["nodes"]
    edges: list[dict[str, Any]] = model["edges"]
    details: dict[str, dict[str, Any]] = model["details"]
    hub_id = model["hub_id"]
    seen_facets: set[str] = set()
    for claim in model["claims"]:
        if claim.kind != EpistemicKind.GAP:
            continue
        facet = claim.facet.value
        if facet in seen_facets:
            continue
        seen_facets.add(facet)
        nid = f"gap:{facet}"
        nodes.append(
            _node(
                nid=nid,
                label=facet_filter_label(facet),
                kind="gap",
                color=ARCHIFY_COLOR["security"],
                layer=2,
                size=0.7,
                facet=facet,
                archify_type="security",
            )
        )
        details[nid] = _detail(
            title=facet_filter_label(facet),
            kind="gap",
            subtitle="hueco · Noc152",
            summary=human_claim(claim),
            facet=facet,
            meta={"tipo": "security", "epistemico": "gap"},
        )
        edges.append({"source": hub_id, "target": nid, "kind": "gap", "label": "sin señales"})


def _payload(
    *,
    engine: str,
    view: str,
    intro: dict[str, Any],
    service: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    details: dict[str, dict[str, Any]],
    facets: list[dict[str, str]],
) -> dict[str, Any]:
    apply_positions(nodes, edges, seed=152)
    return {
        "title": "Noc152",
        "engine": engine,
        "locale": "es",
        "view": view,
        "intro": intro,
        "service": service,
        "nodes": nodes,
        "edges": edges,
        "details": details,
        "coverage": {},
        "facets": facets,
        "trace_paths": [],
        "controls": {
            "orbit": "arrastrar",
            "zoom": "rueda",
            "pan": "click-rueda",
            "select": "click en nodo",
            "expand": "doble click o Ampliar",
            "filter": "filtros",
        },
    }


def build_archify_scene(store: ExpedienteStore, service: Service) -> dict[str, Any]:
    model = _archify_model(store, service)
    health = model["health"]
    return _payload(
        engine="archify",
        view="service",
        intro={
            "title": service.name,
            "body": "IR Archify: componentes e imports. Sin facetas ni huecos operativos.",
            "what_is_it": "",
            "node_legend": [],
            "tips": [],
        },
        service={
            "id": service.service_id,
            "name": service.name,
            "summary": service.summary,
            "health": health["health"],
            "health_label": health["label"],
        },
        nodes=model["nodes"],
        edges=model["edges"],
        details=model["details"],
        facets=[],
    )


def build_combined_scene(store: ExpedienteStore, service: Service) -> dict[str, Any]:
    model = _archify_model(store, service)
    _attach_operational_gaps(model)
    health = model["health"]
    facets = [
        {"id": f.value, "label": facet_filter_label(f.value), "hint": f.value}
        for f in Facet
    ]
    return _payload(
        engine="combined",
        view="service",
        intro={
            "title": service.name,
            "body": "Combinado: arquitectura Archify + huecos y salud Noc152.",
            "what_is_it": "",
            "node_legend": [],
            "tips": [],
        },
        service={
            "id": service.service_id,
            "name": service.name,
            "summary": service.summary,
            "health": health["health"],
            "health_label": health["label"],
        },
        nodes=model["nodes"],
        edges=model["edges"],
        details=model["details"],
        facets=facets,
    )


def build_archify_system(store: ExpedienteStore) -> dict[str, Any]:
    run = store.latest_run() or {}
    source_uri = run.get("source_uri")
    services = [s for s in store.list_services() if not is_noise_service(s.name)]
    services.sort(key=lambda s: s.name.lower())

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    details: dict[str, dict[str, Any]] = {}

    title = source_display_name(source_uri)
    hub_id = "sys:hub"
    nodes.append(
        _node(
            nid=hub_id,
            label=title,
            kind="service",
            color=ARCHIFY_COLOR["hub"],
            layer=0,
            size=1.4,
            facet=None,
            archify_type="backend",
        )
    )
    details[hub_id] = _detail(
        title=title,
        kind="service",
        subtitle="sistema · Archify",
        summary=f"{len(services)} servicios como componentes.",
        facet=None,
    )

    for svc in services:
        health = service_health(store, svc)
        nid = f"svc:{svc.service_id}"
        nodes.append(
            _node(
                nid=nid,
                label=svc.name,
                kind="service",
                color=health["color"],
                layer=1,
                size=1.05,
                facet=None,
                archify_type="backend",
            )
        )
        details[nid] = _detail(
            title=svc.name,
            kind="service",
            subtitle=f"backend · {health['label']}",
            summary=svc.summary or svc.name,
            facet="identity",
            meta={"salud": health["label"], "tipo": "backend"},
            open_service=svc.name,
        )
        edges.append({"source": hub_id, "target": nid, "kind": "contains"})

    return _payload(
        engine="archify",
        view="system",
        intro={
            "title": title,
            "body": f"Mapa Archify: {len(services)} servicios.",
            "what_is_it": "",
            "node_legend": [],
            "tips": [],
        },
        service={"id": "system", "name": "__system__", "summary": "Mapa de servicios."},
        nodes=nodes,
        edges=edges,
        details=details,
        facets=[],
    )
