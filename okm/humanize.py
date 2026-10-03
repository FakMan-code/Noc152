"""Spanish, human-readable copy for Noc152 UI (presentation only)."""

from __future__ import annotations

import re
from typing import Any

from okm.models import Claim, EpistemicKind, Facet, Service

KIND_ES = {
    "observed": "visto en el código",
    "inferred": "lectura probable",
    "gap": "todavía no aparece",
    "service": "pieza central",
    "facet": "área de conocimiento",
    "dependency": "dependencia",
    "claim": "hallazgo",
}

FACET_ES = {
    "identity": {
        "label": "Identidad",
        "hint": "Qué es y para qué sirve",
        "guide": "Acá está el nombre, el propósito y cómo se presenta el proyecto.",
    },
    "topology": {
        "label": "Conexiones",
        "hint": "De qué depende y a qué toca",
        "guide": "Paquetes, imports y relaciones con otras piezas.",
    },
    "runtime": {
        "label": "Cómo corre",
        "hint": "Puertos, contenedores, entorno",
        "guide": "Señales de ejecución: Docker, puertos, variables de entorno.",
    },
    "signals": {
        "label": "Señales",
        "hint": "Monitoreo, logs, alertas",
        "guide": "Qué miraría un NOC para saber si está sano. En repos puros suele faltar.",
    },
    "failure": {
        "label": "Cuando falla",
        "hint": "Incidentes y recuperación",
        "guide": "Runbooks, errores conocidos, caminos de recuperación. También suele faltar en repo-only.",
    },
}

GAP_REASON_ES = {
    "source_not_in_scope": "esta demo solo lee el repositorio; esa info viviría en ops/monitoreo",
    "not_found_in_source": "buscamos señales en el repo y no aparecieron",
}

_PRED_TEMPLATES = {
    "package_name": "Se llama «{obj}».",
    "documented_title": "En la documentación aparece como «{obj}».",
    "module_path": "El módulo principal parece ser «{obj}».",
    "likely_purpose": "{obj}",
    "depends_on_package": "Necesita el paquete Python «{obj}» para funcionar.",
    "requires_package": "Declara el requerimiento «{obj}».",
    "imports_module": "Importa el módulo «{obj}».",
    "references_url": "Menciona la URL «{obj}».",
    "container_base_image": "Usa la imagen de contenedor «{obj}».",
    "exposes_port": "Expone el puerto «{obj}».",
    "facet_uncovered": "En este repo no hay señales de «{facet}».",
    "facet_incomplete": "Todavía no encontramos señales claras de «{facet}».",
}


def clean_markdown(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def kind_label(kind: str) -> str:
    return KIND_ES.get(kind, kind)


def facet_label(facet: str) -> str:
    return FACET_ES.get(facet, {}).get("label", facet)


def human_claim(claim: Claim) -> str:
    obj = clean_markdown(claim.object_value or "")
    facet = facet_label(claim.facet.value)
    if claim.predicate == "likely_purpose" and obj:
        low = obj.lower()
        if "httpx" in low or "http client" in low:
            text = (
                "Sirve para que programas en Python hagan pedidos HTTP "
                "(llamar APIs), con modo sync y async, e incluso una CLI."
            )
        else:
            text = f"Según el README, su propósito sería: {obj}"
    else:
        tpl = _PRED_TEMPLATES.get(claim.predicate)
        if tpl:
            try:
                text = tpl.format(obj=obj or "?", facet=facet.lower())
            except (KeyError, ValueError):
                text = claim.statement
        else:
            text = claim.statement

    text = clean_markdown(text)

    # Light touch-ups for leftover English extractor phrasing
    replacements = (
        ("Python project name:", "Se llama"),
        ("Documented title:", "Título documentado:"),
        ("Declares Python dependency:", "Depende de"),
        ("Declares Python requirement:", "Requiere"),
        ("Python import:", "Importa"),
        ("Likely purpose from README:", ""),
        ("No repository signals for facet", "No hay señales en el repo para"),
        ("Missing observed signals for facet", "Faltan señales observadas de"),
        ("in this source set", ""),
    )
    for a, b in replacements:
        if a in text:
            text = text.replace(a, b).strip(" :")

    if claim.kind == EpistemicKind.GAP and claim.gap_reason:
        reason = GAP_REASON_ES.get(claim.gap_reason, claim.gap_reason)
        text = f"{text} ({reason})"

    # Soften robotic tone
    text = text.strip()
    if text and not text.endswith((".", "?", "!")):
        text += "."
    return text


# Friendly blurbs for well-known public demos (presentation only).
_SERVICE_BLURBS: dict[str, str] = {
    "frontend": (
        "La tienda que ve el usuario: la web de Online Boutique. "
        "Habla con el resto de microservicios para mostrar productos, carrito y checkout."
    ),
    "productcatalogservice": (
        "Catálogo de productos: responde qué hay en venta, precios y detalle de cada ítem."
    ),
    "cartservice": "Carrito de compras: guarda qué agregó el usuario antes de pagar.",
    "checkoutservice": (
        "Checkout: arma el pedido, coordina pago, envío y confirma la compra."
    ),
    "paymentservice": "Pagos: simula cobrar la compra (demo, no es un banco real).",
    "shippingservice": "Envíos: calcula/simula el costo y la logística de entrega.",
    "emailservice": "Emails: manda el mail de confirmación del pedido (en la demo).",
    "currencyservice": "Monedas: convierte precios entre divisas.",
    "recommendationservice": "Recomendaciones: sugiere otros productos según lo que mirás.",
    "adservice": "Anuncios: muestra ads/contextuales en la tienda demo.",
    "loadgenerator": "Generador de carga: inventa tráfico falso para probar el sistema.",
    "shoppingassistantservice": "Asistente de compras: ayuda al usuario a elegir productos.",
    "httpx": (
        "HTTPX no es una app que corre sola: es una biblioteca Python (cliente HTTP) "
        "que otros programas usan para llamar APIs."
    ),
    "okm": (
        "OKM / Noc152: el motor que estás usando. Lee un repo, arma un expediente "
        "(servicios, claims, evidencia) y lo muestra en un mapa 3D con preguntas."
    ),
    "proyecto-noc-152": (
        "Este mismo proyecto: Operational Knowledge Motor + briefing Noc152."
    ),
}

_NOISE_SERVICES = {"helm-chart", "src", "microservices-demo"}


def is_noise_service(name: str) -> bool:
    return name.lower() in _NOISE_SERVICES


def service_blurb(name: str) -> str | None:
    return _SERVICE_BLURBS.get(name.lower())


def human_summary(service: Service) -> str:
    name = service.name.lower()
    blurb = service_blurb(name)
    if blurb:
        return blurb

    raw = clean_markdown(service.summary or "")
    if not raw:
        return (
            f"«{service.name}» es un servicio que el motor reconoció en este repositorio "
            "(por un manifiesto tipo Dockerfile, go.mod, package.json, etc.)."
        )

    if "http client" in raw.lower() or "httpx" in raw.lower():
        return _SERVICE_BLURBS["httpx"]

    if len(raw) > 280:
        raw = raw[:277] + "…"
    return (
        f"Esto es lo que entendimos de «{service.name}»: {raw} "
        "Sale del README/código del repo, no de un catálogo de producto."
    )


def system_intro(*, source_uri: str | None, service_names: list[str]) -> dict[str, Any]:
    names = ", ".join(service_names[:8])
    more = f" y {len(service_names) - 8} más" if len(service_names) > 8 else ""
    return {
        "title": "Mapa del sistema",
        "body": (
            f"Este repo ({source_uri or 'local'}) es la demo pública Online Boutique de Google: "
            "una tienda online partida en microservicios. Cada nodo naranja es un servicio distinto "
            "(frontend, carrito, pagos, envíos…). Click en uno para entrar a su expediente."
        ),
        "what_is_it": (
            "No es una sola app monolítica: es un sistema. "
            f"Servicios en el mapa: {names}{more}."
        ),
        "node_legend": [
            {
                "kind": "service",
                "label": "Violeta — hub del sistema",
                "text": "El nodo principal del mapa (Online Boutique), no un estado de salud.",
            },
            {
                "kind": "facet",
                "label": "Azul — área",
                "text": "Solo aparece cuando entrás a un servicio concreto.",
            },
            {
                "kind": "dependency",
                "label": "Celeste — dependencia",
                "text": "Paquetes/libs que ese servicio declara.",
            },
            {
                "kind": "claim",
                "label": "Gris — hallazgo",
                "text": "Algo concreto del expediente, con evidencia si hay.",
            },
        ],
        "tips": [
            "Empezá por frontend: es la cara de la tienda.",
            "Después mirá checkoutservice / paymentservice / cartservice.",
            "Usá el selector «Sistema» para volver al mapa completo.",
        ],
    }


def brief_intro(service: Service, *, source_uri: str | None = None) -> dict[str, Any]:
    """Onboarding card so the map is understandable without knowing the repo."""
    what = human_summary(service)
    src = source_uri or "repositorio local"
    return {
        "title": f"Servicio: {service.name}",
        "body": (
            f"Entraste al expediente de «{service.name}» dentro de {src}. "
            "El centro es este microservicio; alrededor están áreas de conocimiento "
            "y hallazgos con evidencia del código."
        ),
        "what_is_it": what,
        "node_legend": [
            {
                "kind": "facet",
                "label": "Azul — área",
                "text": "Una pregunta típica de NOC (qué es, de qué depende, cómo falla…).",
            },
            {
                "kind": "dependency",
                "label": "Celeste — dependencia",
                "text": "Otro paquete o módulo que necesita para trabajar.",
            },
            {
                "kind": "claim",
                "label": "Gris — hallazgo",
                "text": "Algo concreto que vimos o inferimos, con link a archivo si hay.",
            },
        ],
        "tips": [
            "Click en un nodo para leer en español qué significa.",
            "Volvé a «Sistema» en el selector para ver todos los microservicios.",
            "«Traza» anima el camino desde el servicio hacia afuera.",
        ],
    }


def humanize_ask_answer(
    *,
    service_name: str,
    hits: list[dict[str, Any]],
    question: str,
) -> str:
    if not hits:
        return (
            f"No encontré nada útil en el expediente de {service_name} para «{question}». "
            "Probá preguntar qué es, de qué depende, si hay monitoreo, o qué huecos tiene."
        )

    lines = [
        f"Mirando el expediente de {service_name}, esto es lo más cercano a tu pregunta:"
    ]
    for h in hits[:5]:
        kind = kind_label(h["kind"])
        facet = facet_label(h["facet"])
        stmt = h.get("statement_es") or h.get("statement") or ""
        stmt = clean_markdown(stmt)
        ref = ""
        if h.get("evidence"):
            ref = f"  | evidencia: {h['evidence'][0]['ref']}"
        lines.append(f"• ({kind} · {facet}) {stmt}{ref}")

    obs = sum(1 for h in hits if h["kind"] == "observed")
    gaps = sum(1 for h in hits if h["kind"] == "gap")
    foot = []
    if obs:
        foot.append(f"{obs} con evidencia en el repo")
    if gaps:
        foot.append(f"{gaps} hueco(s) explícito(s)")
    if foot:
        lines.append("En resumen: " + "; ".join(foot) + ".")
    return "\n".join(lines)
