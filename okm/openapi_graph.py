"""Project an OpenAPI 3.x document into the Noc152 3D graph.

Shows the *contract* surface: API hub → tags (services) → operations → schemas.
This is intentionally different from Archify (deploy topology) and Noc152 (expediente).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from okm.health import health_legend, status_color, status_label
from okm.layout3d import apply_positions

_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "trace")
_REF_RE = re.compile(r"#/components/schemas/([^/\s\"']+)")
_PKG_DOCS = Path(__file__).resolve().parent.parent / "docs" / "openapi"

EDGE_COLOR = "#3a3a3a"
EDGE_SCHEMA = "#475569"


def _openapi_roots(workspace: Path | None = None) -> list[Path]:
    roots: list[Path] = []
    if workspace is not None:
        ws = workspace.expanduser().resolve()
        roots.append(ws / "openapi")
        roots.append(ws)
    roots.append(_PKG_DOCS)
    return roots


def _spec_id(path: Path) -> str:
    name = path.name.lower()
    if "noc152" in name or "briefing" in name:
        return "noc152"
    if "martian" in name:
        return "martian-bank"
    if "microservices" in name or "boutique" in name:
        return "microservices-demo"
    stem = path.stem  # strips .json
    if stem.lower().endswith(".openapi"):
        stem = stem[: -len(".openapi")]
    elif stem.lower().endswith("openapi"):
        stem = stem[: -len("openapi")].rstrip(".-_")
    return (stem or "openapi").replace(" ", "-").lower()


def _scan_openapi_dir(root: Path) -> list[tuple[Path, str]]:
    patterns = ("*.openapi.json", "openapi.json", "swagger.json", "*openapi*.json")
    found: list[Path] = []
    if not root.is_dir():
        return []
    for pattern in patterns:
        found.extend(root.glob(pattern))
    out: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for path in found:
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append((path, _spec_id(path)))
    return out


def _spec_entry(path: Path, sid: str) -> dict[str, Any]:
    title = sid
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        title = str((data.get("info") or {}).get("title") or sid)
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {
        "id": sid,
        "title": title,
        "path": str(path),
        "url": f"/api/openapi/{sid}",
        "docs_url": f"/docs/api?spec={sid}",
        "local": False,
    }


def list_openapi_specs(workspace: Path | None = None) -> list[dict[str, Any]]:
    """Discover OpenAPI JSON for this workspace — no cross-demo bleed.

    If the workspace (or its openapi/) has specs, those win. Bundled product
    demos (Martian / Boutique) are only used as fallback when the workspace
    has none. The Noc152 briefing spec stays available as brain contract.
    """
    local_by_id: dict[str, dict[str, Any]] = {}
    bundled_by_id: dict[str, dict[str, Any]] = {}

    if workspace is not None:
        ws = workspace.expanduser().resolve()
        for root in (ws / "openapi", ws):
            for path, sid in _scan_openapi_dir(root):
                if sid in local_by_id:
                    continue
                entry = _spec_entry(path, sid)
                entry["local"] = True
                local_by_id[sid] = entry

    for path, sid in _scan_openapi_dir(_PKG_DOCS):
        if sid in bundled_by_id:
            continue
        bundled_by_id[sid] = _spec_entry(path, sid)

    by_id: dict[str, dict[str, Any]] = dict(local_by_id)

    # Always allow the brain OpenAPI (Noc152 briefing) alongside a product spec.
    if "noc152" not in by_id and "noc152" in bundled_by_id:
        by_id["noc152"] = bundled_by_id["noc152"]

    if not local_by_id:
        # No local product contract: pick bundled by workspace hint, else all.
        hint = _workspace_spec_hint(workspace)
        if hint and hint in bundled_by_id:
            by_id[hint] = bundled_by_id[hint]
        elif hint == "noc152":
            pass  # already added
        else:
            for sid, entry in bundled_by_id.items():
                by_id.setdefault(sid, entry)

    order = {"noc152": 0, "martian-bank": 1, "microservices-demo": 2}
    return sorted(by_id.values(), key=lambda s: (order.get(s["id"], 9), s["title"].lower()))


def _workspace_spec_hint(workspace: Path | None) -> str | None:
    if workspace is None:
        return None
    name = workspace.expanduser().resolve().name.lower().lstrip(".")
    if "noc152" in name:
        return "noc152"
    if "martian" in name:
        return "martian-bank"
    if "boutique" in name or "microservices" in name:
        return "microservices-demo"
    if "httpx" in name:
        return None
    return None


def resolve_openapi_spec(spec_id: str, workspace: Path | None = None) -> Path | None:
    want = (spec_id or "").strip().lower()
    if not want:
        return find_openapi_spec(workspace)
    for item in list_openapi_specs(workspace):
        if item["id"] == want:
            return Path(item["path"])
    # Last resort: bundled by id (explicit request)
    for path, sid in _scan_openapi_dir(_PKG_DOCS):
        if sid == want:
            return path
    return None


def find_openapi_spec(workspace: Path | None = None) -> Path | None:
    """Product contract for this root — never pick another demo's bundled spec."""
    specs = list_openapi_specs(workspace)
    if not specs:
        return None
    # Local product specs first (exclude brain-only noc152 if others exist)
    local_product = [
        s for s in specs if s.get("local") and s["id"] != "noc152"
    ]
    if local_product:
        return Path(local_product[0]["path"])
    hint = _workspace_spec_hint(workspace)
    if hint:
        for item in specs:
            if item["id"] == hint:
                return Path(item["path"])
    for item in specs:
        if item["id"] != "noc152":
            return Path(item["path"])
    return Path(specs[0]["path"])

def load_openapi_spec(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("OpenAPI spec must be a JSON object")
    if not (data.get("openapi") or data.get("swagger")):
        raise ValueError("missing openapi/swagger version field")
    return data


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", text.strip().lower()).strip("-")
    return s or "node"


def _clip(text: str, n: int = 26) -> str:
    text = text.strip()
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def _collect_schema_refs(obj: Any, out: set[str]) -> None:
    if isinstance(obj, dict):
        ref = obj.get("$ref")
        if isinstance(ref, str):
            m = _REF_RE.search(ref)
            if m:
                out.add(m.group(1))
        for v in obj.values():
            _collect_schema_refs(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_schema_refs(item, out)


def _add_node(
    nodes: list[dict[str, Any]],
    details: dict[str, dict[str, Any]],
    *,
    nid: str,
    kind: str,
    label: str,
    layer: int,
    health: str,
    subtitle: str = "",
    summary: str = "",
    meta: dict[str, Any] | None = None,
    sections: list[dict[str, Any]] | None = None,
    size: float = 1.0,
) -> None:
    if health == "principal":
        size = max(size, 1.35)
    nodes.append(
        {
            "id": nid,
            "kind": kind,
            "label": _clip(label),
            "layer": layer,
            "color": status_color(health),
            "size": size,
            "facet": kind,
            "health": health,
            "health_label": status_label(health),
            "sublabel": subtitle,
        }
    )
    details[nid] = {
        "title": label,
        "kind": kind,
        "kind_label": kind,
        "subtitle": " · ".join(x for x in [subtitle, kind, status_label(health)] if x),
        "summary": summary or subtitle or label,
        "meta": {
            "estado": status_label(health),
            "tipo": kind,
            "id": nid,
            **(meta or {}),
        },
        "sections": sections or [],
        "facet": kind,
        "openapi": {"type": kind, "health": health},
    }


def openapi_to_graph(spec: dict[str, Any], *, engine: str = "openapi", source: str | None = None) -> dict[str, Any]:
    info = spec.get("info") or {}
    title = str(info.get("title") or "OpenAPI")
    version = str(info.get("version") or "")
    description = str(info.get("description") or "")
    paths = spec.get("paths") or {}
    tags_decl = {str(t.get("name")): t for t in (spec.get("tags") or []) if isinstance(t, dict) and t.get("name")}
    schemas = ((spec.get("components") or {}).get("schemas")) or {}
    servers = [s for s in (spec.get("servers") or []) if isinstance(s, dict)]

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    details: dict[str, dict[str, Any]] = {}

    hub_id = "api"
    _add_node(
        nodes,
        details,
        nid=hub_id,
        kind="api",
        label=title,
        layer=0,
        health="principal",
        subtitle=f"OpenAPI {spec.get('openapi') or spec.get('swagger') or ''} {version}".strip(),
        summary=description or title,
        meta={"version": version},
        sections=[
            {
                "title": "Contrato",
                "items": [
                    {
                        "statement": f"{title} · v{version}" if version else title,
                        "kind": "observed",
                    },
                    *([{ "statement": description, "kind": "inferred" }] if description else []),
                    *([{ "statement": f"Fuente: {source}", "kind": "observed" }] if source else []),
                ],
            }
        ],
        size=1.4,
    )

    tag_ids: dict[str, str] = {}
    used_tags: set[str] = set()

    # First pass: discover tags from operations.
    operations: list[tuple[str, str, dict[str, Any]]] = []
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method in _HTTP_METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            operations.append((str(path), method, op))
            for tag in op.get("tags") or []:
                used_tags.add(str(tag))

    if not used_tags and tags_decl:
        used_tags = set(tags_decl.keys())

    for tag in sorted(used_tags):
        tid = f"tag:{_slug(tag)}"
        tag_ids[tag] = tid
        decl = tags_decl.get(tag) or {}
        _add_node(
            nodes,
            details,
            nid=tid,
            kind="tag",
            label=tag,
            layer=1,
            health="ok",
            subtitle="tag / servicio API",
            summary=str(decl.get("description") or f"Tag OpenAPI · {tag}"),
            meta={"tag": tag},
            sections=[
                {
                    "title": "Tag",
                    "items": [
                        {"statement": tag, "kind": "observed"},
                        *(
                            [{"statement": str(decl["description"]), "kind": "inferred"}]
                            if decl.get("description")
                            else []
                        ),
                    ],
                }
            ],
            size=1.1,
        )
        edges.append(
            {
                "id": f"{hub_id}->{tid}",
                "source": hub_id,
                "target": tid,
                "kind": "exposes",
                "label": "tag",
                "color": EDGE_COLOR,
            }
        )

    for i, server in enumerate(servers[:6]):
        url = str(server.get("url") or f"server-{i}")
        sid = f"server:{_slug(url)}"
        _add_node(
            nodes,
            details,
            nid=sid,
            kind="server",
            label=str(server.get("description") or url),
            layer=1,
            health="ok",
            subtitle=url,
            summary=url,
            meta={"url": url},
            size=0.95,
        )
        edges.append(
            {
                "id": f"{hub_id}->{sid}",
                "source": hub_id,
                "target": sid,
                "kind": "serves",
                "label": "server",
                "color": EDGE_COLOR,
            }
        )

    schema_touched: set[str] = set()
    for path, method, op in operations:
        op_id = str(op.get("operationId") or f"{method}:{path}")
        nid = f"op:{_slug(op_id)}"
        summary = str(op.get("summary") or op_id)
        label = f"{method.upper()} {_clip(path, 18)}"
        refs: set[str] = set()
        _collect_schema_refs(op, refs)
        schema_touched |= refs

        op_tags = [str(t) for t in (op.get("tags") or [])]
        parents = [tag_ids[t] for t in op_tags if t in tag_ids] or [hub_id]

        _add_node(
            nodes,
            details,
            nid=nid,
            kind="operation",
            label=label,
            layer=2,
            health="ok",
            subtitle=summary,
            summary=summary,
            meta={"method": method.upper(), "path": path, "operationId": op_id},
            sections=[
                {
                    "title": "Operación",
                    "items": [
                        {"statement": f"{method.upper()} {path}", "kind": "observed"},
                        {"statement": summary, "kind": "inferred"},
                        *[{"statement": f"tag: {t}", "kind": "observed"} for t in op_tags],
                        *[{"statement": f"schema: {s}", "kind": "observed"} for s in sorted(refs)],
                    ],
                }
            ],
            size=0.85,
        )
        for parent in parents:
            edges.append(
                {
                    "id": f"{parent}->{nid}",
                    "source": parent,
                    "target": nid,
                    "kind": "operation",
                    "label": method.upper(),
                    "color": EDGE_COLOR,
                }
            )
        for schema_name in sorted(refs):
            edges.append(
                {
                    "id": f"{nid}->schema:{_slug(schema_name)}",
                    "source": nid,
                    "target": f"schema:{_slug(schema_name)}",
                    "kind": "schema",
                    "label": "$ref",
                    "color": EDGE_SCHEMA,
                }
            )

    for name in sorted(set(schemas) | schema_touched):
        sid = f"schema:{_slug(name)}"
        schema = schemas.get(name) if isinstance(schemas.get(name), dict) else {}
        props = list((schema or {}).get("properties") or {})
        _add_node(
            nodes,
            details,
            nid=sid,
            kind="schema",
            label=name,
            layer=3,
            health="ok",
            subtitle="components.schemas",
            summary=f"Schema {name}" + (f" · {', '.join(props[:6])}" if props else ""),
            meta={"schema": name, "properties": props[:12]},
            sections=[
                {
                    "title": "Schema",
                    "items": [
                        {"statement": name, "kind": "observed"},
                        *[{"statement": f"prop: {p}", "kind": "inferred"} for p in props[:8]],
                    ],
                }
            ],
            size=0.8,
        )
        # Ensure orphan schemas still hang from the hub.
        if not any(e["target"] == sid for e in edges):
            edges.append(
                {
                    "id": f"{hub_id}->{sid}",
                    "source": hub_id,
                    "target": sid,
                    "kind": "schema",
                    "label": "schema",
                    "color": EDGE_SCHEMA,
                }
            )

    # Drop dangling schema edges if schema node somehow missing (shouldn't happen).
    node_ids = {n["id"] for n in nodes}
    edges = [e for e in edges if e["source"] in node_ids and e["target"] in node_ids]

    apply_positions(nodes, edges, seed=314)

    n_ops = len(operations)
    n_tags = len(tag_ids)
    n_schemas = len([n for n in nodes if n["kind"] == "schema"])
    facets = [
        {"id": "api", "label": "api", "hint": "documento OpenAPI"},
        {"id": "tag", "label": "tag", "hint": "agrupa operaciones (a menudo ≈ servicio)"},
        {"id": "operation", "label": "operation", "hint": "método + path"},
        {"id": "schema", "label": "schema", "hint": "components.schemas"},
        {"id": "server", "label": "server", "hint": "servers[]"},
    ]

    return {
        "title": "Noc152",
        "engine": engine,
        "locale": "es",
        "view": "openapi",
        "intro": {
            "title": title,
            "body": (
                f"{n_tags} tags · {n_ops} operaciones · {n_schemas} schemas · contrato OpenAPI"
            ),
            "what_is_it": (
                "Vista del contrato HTTP: no es el deploy (Archify) ni el expediente (Noc152). "
                "Muestra qué expone la API y qué modelos usa."
            ),
            "node_legend": health_legend(),
            "tips": [],
        },
        "service": {
            "id": "openapi",
            "name": title,
            "summary": title,
        },
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
            "filter": "tipos OpenAPI",
        },
        "openapi": {
            "title": title,
            "version": version,
            "source": source,
            "operation_count": n_ops,
            "tag_count": n_tags,
            "schema_count": n_schemas,
            "server_count": len(servers),
            "health_legend": health_legend(),
        },
    }
