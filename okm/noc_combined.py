"""Combinado NOC: mapa de la app en lenguaje de producto.

Muestra servicios y dependencias con roles humanos (qué hace cada pieza).
Los endpoints OpenAPI viven en el motor OpenAPI, no acá — evita ruido.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from okm.health import service_health, status_color, status_label
from okm.humanize import is_noise_service, source_display_name
from okm.layout3d import apply_positions
from okm.models import Service
from okm.node_sources import NODE_SOURCE_MAP
from okm.store import ExpedienteStore

# Nombre corto en el grafo + una línea de “qué es esto”.
_SERVICE_STORY: dict[str, dict[str, str]] = {
    # Martian Bank
    "ui": {
        "role": "App web",
        "blurb": "Pantalla del banco: donde el cliente se loguea, ve cuentas, transfiere y pide préstamos.",
    },
    "customer-auth": {
        "role": "Login",
        "blurb": "Registra usuarios y emite el token JWT. Sin esto nadie entra a la app.",
    },
    "dashboard": {
        "role": "Puerta API",
        "blurb": "Recibe pedidos de la UI y habla con cuentas, transferencias y préstamos (HTTP o gRPC).",
    },
    "accounts": {
        "role": "Cuentas",
        "blurb": "Crea y consulta cuentas: número, saldo, moneda. El corazón del dinero en el banco.",
    },
    "transactions": {
        "role": "Transferencias",
        "blurb": "Mueve plata entre cuentas. Si falla, el cliente no puede pagar ni enviar fondos.",
    },
    "loan": {
        "role": "Préstamos",
        "blurb": "Solicitud y gestión de préstamos. Depende de que existan cuentas válidas.",
    },
    "atm-locator": {
        "role": "Cajeros",
        "blurb": "Busca ATMs (incluso ‘interplanetarios’ en la demo). Complemento, no el core del banco.",
    },
    # Online Boutique (por si volvés a esa demo)
    "frontend": {"role": "Tienda web", "blurb": "UI de la boutique."},
    "checkoutservice": {"role": "Checkout", "blurb": "Arma el pedido y orquesta pago/envío."},
    "paymentservice": {"role": "Pagos", "blurb": "Cobra la compra."},
    "cartservice": {"role": "Carrito", "blurb": "Guarda ítems del carrito."},
    "productcatalogservice": {"role": "Catálogo", "blurb": "Lista y detalla productos."},
    "currencyservice": {"role": "Moneda", "blurb": "Convierte precios."},
    "shippingservice": {"role": "Envíos", "blurb": "Cotiza y despacha."},
    "emailservice": {"role": "Email", "blurb": "Confirmación de compra."},
    "recommendationservice": {"role": "Recomendaciones", "blurb": "Sugiere productos."},
    "adservice": {"role": "Anuncios", "blurb": "Ads contextuales."},
    "loadgenerator": {"role": "Carga", "blurb": "Genera tráfico de prueba."},
}

_CRITICALITY: dict[str, str] = {
    "ui": "alta",
    "customer-auth": "alta",
    "accounts": "alta",
    "transactions": "alta",
    "dashboard": "media",
    "loan": "media",
    "atm-locator": "baja",
    "frontend": "alta",
    "checkoutservice": "alta",
    "paymentservice": "alta",
    "cartservice": "alta",
    "productcatalogservice": "media",
    "currencyservice": "media",
    "shippingservice": "media",
    "emailservice": "media",
    "recommendationservice": "baja",
    "adservice": "baja",
    "loadgenerator": "baja",
}

_KNOWN_DEPS: dict[str, list[str]] = {
    "ui": ["customer-auth", "dashboard", "atm-locator"],
    "dashboard": ["accounts", "transactions", "loan"],
    "transactions": ["accounts"],
    "loan": ["accounts"],
    "frontend": [
        "productcatalogservice",
        "cartservice",
        "currencyservice",
        "recommendationservice",
        "shippingservice",
        "checkoutservice",
        "adservice",
    ],
    "checkoutservice": [
        "productcatalogservice",
        "cartservice",
        "currencyservice",
        "paymentservice",
        "shippingservice",
        "emailservice",
    ],
    "recommendationservice": ["productcatalogservice"],
}

_PRODUCT_STORY: dict[str, dict[str, str]] = {
    "martian-bank-demo": {
        "title": "Martian Bank",
        "body": (
            "Demo de banco online (Cisco): el cliente entra por la app web, "
            "se autentica, ve cuentas, hace transferencias, pide prestamos y busca cajeros. "
            "Cada esfera es un microservicio de esa historia."
        ),
        "flow": "App web -> Login -> Puerta API -> Cuentas / Transferencias / Prestamos (+ Cajeros)",
    },
    "microservices-demo": {
        "title": "Online Boutique",
        "body": "Tienda demo de Google: catalogo, carrito, checkout, pago y envio.",
        "flow": "Tienda -> Catalogo/Carrito -> Checkout -> Pago/Envio",
    },
    "proyecto-noc-152": {
        "title": "Noc152",
        "body": (
            "Expediente operacional + mapa 3D: ingestás un repo, guardás claims con evidencia "
            "y explorás la app en Combinado (roles), Archify, Noc152 o OpenAPI."
        ),
        "flow": "Ingest → Expediente → Mapa (Combinado) → Asistente",
    },
    "noc152": {
        "title": "Noc152",
        "body": (
            "Expediente operacional + mapa 3D: ingestás un repo, guardás claims con evidencia "
            "y explorás la app en Combinado (roles), Archify, Noc152 o OpenAPI."
        ),
        "flow": "Ingest → Expediente → Mapa (Combinado) → Asistente",
    },
}

# Capas lógicas del propio Noc152 (mono-repo → historia legible en Combinado).
def self_map_part_count() -> int:
    """Logical layers shown on the Noc152 self-map (not microservices)."""
    return len(_SELF_ROLES)


_SELF_ROLES: list[dict[str, Any]] = [
    {
        "id": "role:ingest",
        "role": "Ingest",
        "blurb": "Lee un repo (local o git), detecta servicios por manifiestos y extrae claims.",
        "deps": [],
    },
    {
        "id": "role:expediente",
        "role": "Expediente",
        "blurb": "SQLite + blobs: servicios, claims, evidencia y gaps con procedencia.",
        "deps": ["role:ingest"],
    },
    {
        "id": "role:combinado",
        "role": "Combinado",
        "blurb": "Mapa historia: roles humanos, formas y deps. Arranque por defecto del briefing.",
        "deps": ["role:expediente"],
    },
    {
        "id": "role:archify",
        "role": "Archify",
        "blurb": "Proyecta un IR de arquitectura curado al mismo visor 3D.",
        "deps": ["role:expediente"],
    },
    {
        "id": "role:openapi",
        "role": "OpenAPI",
        "blurb": "Contrato HTTP: tags, operations y schemas (borde, no cerebro).",
        "deps": ["role:expediente"],
    },
    {
        "id": "role:asistente",
        "role": "Asistente",
        "blurb": "Preguntas grounded en el dossier del mapa + Ollama opcional.",
        "deps": ["role:expediente", "role:combinado"],
    },
    {
        "id": "role:serve",
        "role": "Briefing",
        "blurb": "UI local Three.js: selector de motor, drill por capas y panel de detalle.",
        "deps": ["role:combinado", "role:archify", "role:openapi", "role:asistente"],
    },
]

_EDGE = "#3a3a3a"
_EDGE_DEP = "#64748b"


def _short(name: str) -> str:
    if name.lower().endswith("service") and len(name) > 7:
        return name[: -len("service")]
    return name


def _clip(text: str, n: int = 26) -> str:
    text = text.strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _criticality(service_name: str) -> str:
    key = service_name.lower()
    if key in _CRITICALITY:
        return _CRITICALITY[key]
    bare = key.removesuffix("-service").removesuffix("service")
    return _CRITICALITY.get(bare, _CRITICALITY.get(f"{bare}-service", "media"))


def _story(service_name: str) -> dict[str, str]:
    key = service_name.lower()
    if key in _SERVICE_STORY:
        return _SERVICE_STORY[key]
    bare = key.removesuffix("-service")
    return _SERVICE_STORY.get(
        bare,
        {
            "role": _short(service_name),
            "blurb": f"Servicio «{service_name}» del sistema.",
        },
    )


def _product_story(source_uri: str | None, title: str) -> dict[str, str]:
    uri = (source_uri or "").lower().replace("\\", "/")
    title_l = (title or "").lower()
    for key, story in _PRODUCT_STORY.items():
        if key in uri or key in title_l:
            return story
    if "noc" in title_l and "152" in title_l:
        return _PRODUCT_STORY["noc152"]
    return {
        "title": title,
        "body": f"Mapa de servicios de «{title}». Cada nodo es una pieza que habla con otras.",
        "flow": "Producto → servicios → dependencias",
    }


def is_self_map_workspace(
    source_uri: str | None,
    title: str,
    services: list[Service],
    workspace: Path | None = None,
) -> bool:
    """True when the workspace is Noc152 itself (mono-repo → capas lógicas).

    No depende de un servicio llamado «Noc152» (ese nombre es ruido en demos).
    """
    uri = (source_uri or "").lower().replace("\\", "/")
    if "proyecto-noc-152" in uri:
        return True
    if workspace is not None:
        wp = str(workspace.resolve()).lower().replace("\\", "/")
        if "demo_noc152" in wp or wp.rstrip("/").endswith("/.demo_noc152"):
            return True
    # Solo mono-servicio okm (no el label de producto Noc152)
    if len(services) == 1 and services[0].name.lower() == "okm":
        return True
    return False


# Back-compat for callers that used the private name
_is_self_map = is_self_map_workspace


def _append_self_roles(
    *,
    hub_id: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    details: dict[str, dict[str, Any]],
) -> None:
    for role in _SELF_ROLES:
        rid = str(role["id"])
        nodes.append(
            {
                "id": rid,
                "kind": "service",
                "label": _clip(str(role["role"])),
                "layer": 1,
                "color": status_color("neutral"),
                "size": 1.1,
                "facet": "service",
                "service_name": rid,
                "health": "neutral",
                "health_label": status_label("neutral"),
                "criticality": "media",
                "role": str(role["role"]),
            }
        )
        edges.append(
            {
                "id": f"{hub_id}->{rid}",
                "source": hub_id,
                "target": rid,
                "kind": "contains",
                "label": "",
                "color": _EDGE,
            }
        )
        srcs = NODE_SOURCE_MAP.get(rid, []) or NODE_SOURCE_MAP.get(
            str(role["role"]).lower(), []
        )
        sections: list[dict[str, Any]] = [
            {
                "title": "Qué hace",
                "items": [{"statement": str(role["blurb"]), "kind": "observed"}],
            }
        ]
        if srcs:
            sections.append(
                {
                    "title": "Código fuente",
                    "items": [
                        {
                            "statement": f"Archivo: {p}",
                            "kind": "observed",
                        }
                        for p in srcs
                    ],
                }
            )
        details[rid] = {
            "title": str(role["role"]),
            "kind": "service",
            "kind_label": "capa",
            "subtitle": "pieza de Noc152",
            "summary": str(role["blurb"]),
            "meta": {
                "rol": str(role["role"]),
                "tipo": "capa lógica",
                "fuentes": ", ".join(srcs) if srcs else "—",
            },
            "sections": sections,
            "facet": "service",
            "sources": srcs,
        }
    for role in _SELF_ROLES:
        rid = str(role["id"])
        for dep in role.get("deps") or []:
            dep_id = str(dep)
            edges.append(
                {
                    "id": f"{rid}->{dep_id}",
                    "source": rid,
                    "target": dep_id,
                    "kind": "depends",
                    "label": "",
                    "color": _EDGE_DEP,
                }
            )


def _top_evidence_paths(
    store: ExpedienteStore, svc: Service, *, limit: int = 3
) -> list[str]:
    """Most-cited code-ish paths under a service folder (for dock + handbook)."""
    prefix = (svc.root_path or svc.name or "").replace("\\", "/").strip("/")
    counts: Counter[str] = Counter()
    for ev in store.list_evidence():
        path = (ev.path or "").replace("\\", "/")
        if not path or not prefix:
            continue
        if not (path == prefix or path.startswith(prefix + "/")):
            continue
        lower = path.lower()
        base = lower.rsplit("/", 1)[-1]
        if base in {"dockerfile", "makefile"} or lower.endswith(
            (".md", ".txt", ".license")
        ):
            continue
        counts[path] += 1

    def sort_key(item: tuple[str, int]) -> tuple[int, int, str]:
        path, n = item
        lower = path.lower()
        if any(
            lower.endswith(s)
            for s in (".py", ".go", ".ts", ".js", ".java", ".rs", ".cs")
        ):
            tier = 0
        elif lower.endswith((".json", ".yaml", ".yml", ".toml", ".proto")):
            tier = 1
        else:
            tier = 2
        return (tier, -n, path)

    return [p for p, _ in sorted(counts.items(), key=sort_key)[:limit]]


def _dep_pairs(services: list[Service]) -> list[tuple[str, str]]:
    names = {s.name.lower(): s.name for s in services}
    pairs: list[tuple[str, str]] = []
    for src, targets in _KNOWN_DEPS.items():
        if src not in names:
            continue
        for dst in targets:
            if dst in names:
                pairs.append((names[src], names[dst]))
    return pairs


# Catálogos conocidos: evita que un servicio suelto (ej. «Noc152») contamine el mapa del banco.
_PRODUCT_SERVICE_ALLOW: dict[str, frozenset[str]] = {
    "martian-bank-demo": frozenset(
        {
            "ui",
            "customer-auth",
            "dashboard",
            "accounts",
            "transactions",
            "loan",
            "atm-locator",
        }
    ),
    "microservices-demo": frozenset(
        {
            "frontend",
            "checkoutservice",
            "paymentservice",
            "cartservice",
            "productcatalogservice",
            "currencyservice",
            "shippingservice",
            "emailservice",
            "recommendationservice",
            "adservice",
            "loadgenerator",
        }
    ),
}


def _filter_product_services(
    source_uri: str | None, title: str, services: list[Service]
) -> list[Service]:
    uri = (source_uri or "").lower().replace("\\", "/")
    title_l = (title or "").lower()
    allow: frozenset[str] | None = None
    for key, names in _PRODUCT_SERVICE_ALLOW.items():
        if key in uri or key in title_l:
            allow = names
            break
    if allow is None:
        return services
    return [s for s in services if s.name.lower() in allow]


def build_noc_combined_system(store: ExpedienteStore, workspace: Path | None = None) -> dict[str, Any]:
    run = store.latest_run() or {}
    source_uri = run.get("source_uri")
    title = source_display_name(source_uri)
    product = _product_story(source_uri, title)
    services = [s for s in store.list_services() if not is_noise_service(s.name)]
    services = _filter_product_services(source_uri, title, services)
    services.sort(key=lambda s: (_criticality(s.name) != "alta", s.name.lower()))
    self_map = _is_self_map(source_uri, title, services, workspace=workspace)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    details: dict[str, dict[str, Any]] = {}

    hub_id = "noc:product"
    nodes.append(
        {
            "id": hub_id,
            "kind": "product",
            "label": _clip(product.get("title") or title, 28),
            "layer": 0,
            "color": status_color("principal"),
            "size": 1.45,
            "facet": "product",
            "health": "principal",
            "health_label": status_label("principal"),
            "role": "producto",
        }
    )
    details[hub_id] = {
        "title": product.get("title") or title,
        "kind": "product",
        "kind_label": "producto",
        "subtitle": "cómo funciona la app",
        "summary": product["body"],
        "meta": {
            "fuente": source_uri or "local",
            "servicios": len(_SELF_ROLES) if self_map else len(services),
        },
        "sections": [
            {
                "title": "Historia del usuario",
                "items": [
                    {"statement": product["body"], "kind": "observed"},
                    {"statement": f"Flujo: {product['flow']}", "kind": "inferred"},
                    {
                        "statement": (
                            "Capas lógicas del propio Noc152 (mono-repo)."
                            if self_map
                            else "Las flechas unen quién necesita a quién. Los endpoints están en el motor OpenAPI."
                        ),
                        "kind": "inferred",
                    },
                ],
            }
        ],
        "facet": "product",
    }

    if self_map:
        _append_self_roles(hub_id=hub_id, nodes=nodes, edges=edges, details=details)
        apply_positions(nodes, edges, seed=152)
        return {
            "title": product.get("title") or title,
            "engine": "combined",
            "locale": "es",
            "view": "system",
            "intro": {
                "title": product.get("title") or title,
                "body": product["body"],
                "what_is_it": (
                    f"{product['flow']}. "
                    f"{len(_SELF_ROLES)} capas · mapa del propio Noc152."
                ),
                "node_legend": [],
                "tips": [],
            },
            "service": {
                "id": "system",
                "name": "__system__",
                "summary": product["body"],
            },
            "nodes": nodes,
            "edges": edges,
            "details": details,
            "facets": [
                {"id": "product", "label": "producto"},
                {"id": "service", "label": "servicio"},
            ],
        }

    svc_node_ids: dict[str, str] = {}

    for svc in services:
        health = service_health(store, svc)
        crit = _criticality(svc.name)
        h = str(health.get("health") or "neutral")
        story = _story(svc.name)
        nid = f"svc:{svc.service_id}"
        svc_node_ids[svc.name] = nid
        nodes.append(
            {
                "id": nid,
                "kind": "service",
                "label": _clip(story["role"]),
                "layer": 1,
                "color": health.get("color") or status_color(h),
                "size": 1.15 if crit == "alta" else 1.0,
                "facet": "service",
                "service_name": svc.name,
                "health": h,
                "health_label": health.get("label") or status_label(h),
                "criticality": crit,
                "role": story["role"],
            }
        )
        edges.append(
            {
                "id": f"{hub_id}->{nid}",
                "source": hub_id,
                "target": nid,
                "kind": "contains",
                "label": "",
                "color": _EDGE,
            }
        )
        key_paths = _top_evidence_paths(store, svc, limit=3)
        sections: list[dict[str, Any]] = [
            {
                "title": "Qué hace",
                "items": [
                    {"statement": story["blurb"], "kind": "observed"},
                    {
                        "statement": f"En el repo: carpeta «{svc.root_path or svc.name}».",
                        "kind": "inferred",
                    },
                ],
            }
        ]
        if key_paths:
            sections.append(
                {
                    "title": "Archivos clave",
                    "items": [
                        {"statement": f"Archivo: {p}", "kind": "observed"}
                        for p in key_paths
                    ],
                }
            )
        details[nid] = {
            "title": story["role"],
            "kind": "service",
            "kind_label": "servicio",
            "subtitle": svc.name,
            "summary": story["blurb"],
            "meta": {
                "servicio": svc.name,
                "rol": story["role"],
                "criticidad": crit,
                "ruta": svc.root_path,
                "fuentes": ", ".join(key_paths) if key_paths else "—",
            },
            "sections": sections,
            "facet": "service",
            "open_service": svc.name,
            "sources": key_paths,
        }

    for src_name, dst_name in _dep_pairs(services):
        src_id = svc_node_ids.get(src_name)
        dst_id = svc_node_ids.get(dst_name)
        if not src_id or not dst_id:
            continue
        src_role = _story(src_name)["role"]
        dst_role = _story(dst_name)["role"]
        edges.append(
            {
                "id": f"dep:{src_name}->{dst_name}",
                "source": src_id,
                "target": dst_id,
                "kind": "depends",
                "label": "",
                "color": _EDGE_DEP,
            }
        )
        # Explicar la flecha en el detalle del origen
        details[src_id].setdefault("sections", []).append(
            {
                "title": f"Usa -> {dst_role}",
                "items": [
                    {
                        "statement": (
                            f"«{src_role}» necesita «{dst_role}» ({dst_name}) "
                            "para completar su trabajo."
                        ),
                        "kind": "inferred",
                    }
                ],
            }
        )

    apply_positions(nodes, edges, seed=152)

    alta = sum(1 for s in services if _criticality(s.name) == "alta")
    return {
        "title": "Noc152",
        "engine": "combined",
        "locale": "es",
        "view": "system",
        "intro": {
            "title": product.get("title") or title,
            "body": product["body"],
            "what_is_it": (
                f"{product['flow']}. "
                f"{len(services)} servicios · {alta} de impacto alto. "
                "Click en un nodo para leer que hace. Endpoints: motor OpenAPI."
            ),
            "node_legend": [],
            "tips": [],
        },
        "service": {
            "id": "system",
            "name": "__system__",
            "summary": product["body"],
        },
        "nodes": nodes,
        "edges": edges,
        "details": details,
        "coverage": {},
        "facets": [
            {"id": "product", "label": "producto", "hint": "la app completa"},
            {"id": "service", "label": "servicio", "hint": "pieza de la historia"},
        ],
        "trace_paths": [],
        "controls": {
            "orbit": "arrastrar",
            "zoom": "rueda",
            "pan": "click-rueda",
            "select": "click en nodo",
            "expand": "doble click o Ampliar",
            "filter": "producto / servicio",
        },
        "noc": {
            "lens": "historia-app",
            "service_count": len(services),
            "critical_high": alta,
        },
    }


def build_noc_combined_service(
    store: ExpedienteStore,
    service: Service,
    workspace: Path | None = None,
) -> dict[str, Any]:
    full = build_noc_combined_system(store, workspace=workspace)
    keep_ids = {n["id"] for n in full["nodes"] if n.get("service_name") == service.name}
    # Include product hub for context + this service + its neighbors
    hub = next((n for n in full["nodes"] if n["id"] == "noc:product"), None)
    neighbors: set[str] = set()
    for e in full["edges"]:
        if e.get("kind") != "depends":
            continue
        for n in full["nodes"]:
            if n["id"] not in keep_ids:
                continue
            if e.get("source") == n["id"]:
                neighbors.add(e["target"])
            if e.get("target") == n["id"]:
                neighbors.add(e["source"])
    keep_ids |= neighbors
    if hub:
        keep_ids.add(hub["id"])

    nodes = [dict(n) for n in full["nodes"] if n["id"] in keep_ids]
    for n in nodes:
        if n.get("service_name") == service.name:
            # Foco de lectura (violeta), no semáforo
            n["health"] = "principal"
            n["health_label"] = "foco"
            n["color"] = status_color("principal")
            n["layer"] = 0
            n["size"] = 1.35
            n["criticality"] = None  # evita anillos de “alerta” por criticidad
        elif n["kind"] == "product":
            n["layer"] = 0
        else:
            n["layer"] = 1
            # Vecinos en neutro: el semáforo solo si hay ops real
            if n.get("health") not in {"alert", "failing", "ok"}:
                n["health"] = "neutral"
                n["health_label"] = status_label("neutral")
                n["color"] = status_color("neutral")
            n["criticality"] = None
    node_ids = {n["id"] for n in nodes}
    edges = [
        e
        for e in full["edges"]
        if e.get("source") in node_ids and e.get("target") in node_ids
    ]
    details = {k: v for k, v in full["details"].items() if k in node_ids}
    apply_positions(nodes, edges, seed=271)
    story = _story(service.name)
    crit = _criticality(service.name)
    full.update(
        {
            "view": "service",
            "intro": {
                "title": story["role"],
                "body": story["blurb"],
                "what_is_it": (
                    f"«{service.name}» · criticidad {crit}. "
                    "Vecinos = de quién depende o quién lo usa."
                ),
                "node_legend": [],
                "tips": [],
            },
            "service": {
                "id": service.service_id,
                "name": service.name,
                "summary": story["blurb"],
                "criticality": crit,
            },
            "nodes": nodes,
            "edges": edges,
            "details": details,
        }
    )
    return full
