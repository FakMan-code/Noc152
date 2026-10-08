"""Operational health colors for Noc152 / Archify 3D nodes.

Semáforo de problemas (solo nodos, no aristas/tráfico):
  violeta (#8b5cf6) — principal (hub del mapa)
  neutro  (#9aa8b8) — sin señal ops (default del mapa)
  verde   (#4ade80) — ok confirmado por ops
  amarillo (#fbbf24) — alerta a revisar
  rojo    (#ef4444) — problema / falla

Verde / amarillo / rojo se reservan al semáforo. El tráfico de aristas
usa otros colores (cyan / lavanda).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from okm.models import Claim, EpistemicKind, Facet, Service
from okm.store import ExpedienteStore

Health = Literal["principal", "ok", "alert", "failing"]

HEALTH_COLOR: dict[str, str] = {
    "principal": "#8b5cf6",
    "neutral": "#9aa8b8",
    "ok": "#4ade80",
    "alert": "#fbbf24",
    "degraded": "#fbbf24",
    "failing": "#ef4444",
    "unknown": "#9aa8b8",
}

HEALTH_LABEL_ES = {
    "principal": "principal",
    "neutral": "sin señal",
    "ok": "ok",
    "alert": "alerta",
    "degraded": "alerta",
    "failing": "problema",
    "unknown": "sin señal",
}

NODE_COLOR = {
    "hub": "#8b5cf6",  # violeta — nodo principal
    "principal": "#8b5cf6",
    "neutral": "#9aa8b8",
    "ok": "#4ade80",
    "facet": "#88a4bf",
    "dependency": "#38bdf8",
    "claim": "#d4d4d4",
    "gap": "#94a3b8",
    "alert": "#fbbf24",
    "failing": "#ef4444",
}

# Solo productores "ops" cuentan para pintar amarillo/rojo.
# Los huecos del scan de repo (coverage.*) no son alertas de producción.
_OPS_PRODUCERS = {
    "ops.alert",
    "ops.incident",
    "ops.monitor",
    "datadog",
    "pagerduty",
    "prometheus",
}

_FAIL_RE = re.compile(
    r"\b(fail|failed|failure|error|exception|panic|outage|crash|sever[eo]|down|timeout)\b",
    re.IGNORECASE,
)


def _from_ops(claim: Claim) -> bool:
    return (claim.producer or "").lower() in _OPS_PRODUCERS or (
        claim.producer or ""
    ).lower().startswith("ops.")


def claim_looks_failing(claim: Claim) -> bool:
    """Rojo solo con falla observada de una fuente ops (no del scan de repo)."""
    if claim.kind != EpistemicKind.OBSERVED:
        return False
    if not _from_ops(claim):
        return False
    if claim.facet == Facet.FAILURE:
        return True
    blob = " ".join(
        filter(None, [claim.statement, claim.predicate, claim.object_value or ""])
    )
    return bool(_FAIL_RE.search(blob))


def claim_is_alert(claim: Claim) -> bool:
    """Amarillo solo con alerta ops no crítica (cuando anexemos monitoreo)."""
    if not _from_ops(claim):
        return False
    if claim.kind == EpistemicKind.GAP:
        return False
    if claim_looks_failing(claim):
        return False
    # severidad liviana / warning si aparece en predicate/object
    blob = " ".join(
        filter(None, [claim.statement, claim.predicate, claim.object_value or ""])
    ).lower()
    return any(w in blob for w in ("warn", "warning", "alerta", "degraded", "elevated"))


def node_color_for_claim(claim: Claim) -> tuple[str, str]:
    if claim_looks_failing(claim):
        return "failing", NODE_COLOR["failing"]
    if claim_is_alert(claim):
        return "alert", NODE_COLOR["alert"]
    if claim.kind == EpistemicKind.GAP:
        return "gap", NODE_COLOR["gap"]
    return "claim", NODE_COLOR["claim"]


def _has_ops_signal(claims: list[Claim]) -> bool:
    for c in claims:
        prod = (c.producer or "").lower()
        if prod.startswith("ops") or prod in {"datadog", "prometheus", "cloudwatch", "pagerduty"}:
            return True
    return False


def service_health(store: ExpedienteStore, service: Service) -> dict[str, Any]:
    claims = store.claims_for(service.service_id)

    failing = [c for c in claims if claim_looks_failing(c)]
    if failing:
        return {
            "health": "failing",
            "color": HEALTH_COLOR["failing"],
            "label": HEALTH_LABEL_ES["failing"],
            "reason": human_fail_reason(failing[0]),
        }

    alerts = [c for c in claims if claim_is_alert(c)]
    if alerts:
        return {
            "health": "alert",
            "color": HEALTH_COLOR["alert"],
            "label": HEALTH_LABEL_ES["alert"],
            "reason": "Hay una alerta ops a revisar (no crítica).",
        }

    if _has_ops_signal(claims):
        return {
            "health": "ok",
            "color": HEALTH_COLOR["ok"],
            "label": HEALTH_LABEL_ES["ok"],
            "reason": "Ops sin alertas ni fallas para este servicio.",
        }

    return {
        "health": "neutral",
        "color": HEALTH_COLOR["neutral"],
        "label": HEALTH_LABEL_ES["neutral"],
        "reason": (
            "Sin señal de monitoreo todavía: color neutro. "
            "Verde/amarillo/rojo quedan para el semáforo cuando haya ops."
        ),
    }


def human_fail_reason(claim: Claim) -> str:
    from okm.humanize import human_claim

    return f"Algo roto según ops: {human_claim(claim)}"


def health_legend() -> list[dict[str, str]]:
    return [
        {
            "kind": "principal",
            "label": "Violeta — principal",
            "text": "Nodo hub del mapa (centro de la vista).",
        },
        {
            "kind": "neutral",
            "label": "Gris — sin señal",
            "text": "Default del mapa sin monitoreo conectado.",
        },
        {
            "kind": "ok",
            "label": "Verde — ok",
            "text": "Semáforo: ops confirma que está bien.",
        },
        {
            "kind": "alert",
            "label": "Amarillo — alerta",
            "text": "Semáforo: alerta ops a revisar.",
        },
        {
            "kind": "failing",
            "label": "Rojo — problema",
            "text": "Semáforo: falla real de ops/producción.",
        },
    ]


def status_color(status: str) -> str:
    return HEALTH_COLOR.get(status, HEALTH_COLOR["neutral"])


def status_label(status: str) -> str:
    return HEALTH_LABEL_ES.get(status, status)
