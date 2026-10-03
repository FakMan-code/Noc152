"""Spanish, human-readable copy for Noc152 UI (presentation only)."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from okm.config import load_config
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

    text = text.strip()
    if text and not text.endswith((".", "?", "!")):
        text += "."
    return text


def noise_service_names() -> set[str]:
    cfg = load_config()
    names = cfg.get("resolve", {}).get("noise_service_names", [])
    return {str(n).lower() for n in names}


def is_noise_service(name: str) -> bool:
    return name.lower() in noise_service_names()


def source_display_name(source_uri: str | None) -> str:
    if not source_uri:
        return "Sistema"
    raw = source_uri.rstrip("/").split("/")[-1]
    if raw.endswith(".git"):
        raw = raw[:-4]
    # Windows path → last segment
    raw = PurePosixPath(raw.replace("\\", "/")).name or raw
    return raw or "Sistema"


def human_summary(service: Service) -> str:
    raw = clean_markdown(service.summary or "")
    if not raw:
        return (
            f"«{service.name}» es un servicio que el motor reconoció en este repositorio "
            "(por un manifiesto tipo Dockerfile, go.mod, package.json, etc.)."
        )
    if len(raw) > 280:
        raw = raw[:277] + "…"
    return (
        f"Esto es lo que entendimos de «{service.name}»: {raw} "
        "Sale del README/código del repo, no de un catálogo externo."
    )


def system_intro(*, source_uri: str | None, service_names: list[str]) -> dict[str, Any]:
    title = source_display_name(source_uri)
    names = ", ".join(service_names[:8])
    more = f" y {len(service_names) - 8} más" if len(service_names) > 8 else ""
    multi = len(service_names) > 1
    return {
        "title": "Mapa del sistema",
        "body": (
            f"Noc152 leyó «{title}» ({source_uri or 'ruta local'}) y armó este mapa. "
            + (
                "Cada nodo es un servicio detectado por manifiestos; click para entrar a su expediente."
                if multi
                else "Por ahora hay un servicio principal; abrilo para ver áreas, hallazgos y evidencia."
            )
        ),
        "what_is_it": (
            f"{'Sistema con varios servicios' if multi else 'Servicio detectado'}: {names}{more}."
        ),
        "node_legend": [
            {
                "kind": "service",
                "label": "Violeta — hub del sistema",
                "text": "Nodo principal del mapa (identidad del source), no un estado de salud.",
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
            "Empezá por el hub violeta o por el servicio que te interese.",
            "Usá el selector «Sistema» para volver al mapa completo.",
            "Preguntá en español: el agente solo usa el expediente.",
        ],
    }


def brief_intro(service: Service, *, source_uri: str | None = None) -> dict[str, Any]:
    what = human_summary(service)
    src = source_uri or "repositorio local"
    return {
        "title": f"Servicio: {service.name}",
        "body": (
            f"Entraste al expediente de «{service.name}» dentro de {src}. "
            "El centro es este servicio; alrededor están áreas de conocimiento "
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
            "Volvé a «Sistema» en el selector para ver todos los servicios.",
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
