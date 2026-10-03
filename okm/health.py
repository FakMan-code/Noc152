"""Operational health colors for Noc152 nodes.

Semántica:
  verde  (#4ade80) — ok
  amarillo (#fbbf24) — alerta a revisar (no crítica) — solo con señal ops real
  rojo   (#ef4444) — algo roto — solo con evidencia de falla real

Hoy el expediente es repo-only (no productivo): sin alertas ni fallas anexadas
todo se pinta ok. El amarillo/rojo quedan listos para cuando enlacemos monitoreo.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from okm.models import Claim, EpistemicKind, Facet, Service
from okm.store import ExpedienteStore

Health = Literal["ok", "alert", "failing"]

HEALTH_COLOR: dict[str, str] = {
    "ok": "#4ade80",
    "alert": "#fbbf24",
    "degraded": "#fbbf24",
    "failing": "#ef4444",
    "unknown": "#4ade80",
}

NODE_COLOR = {
    "hub": "#8b5cf6",  # violeta — nodo principal del sistema
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

HEALTH_LABEL_ES = {
    "ok": "ok",
    "alert": "alerta",
    "degraded": "alerta",
    "failing": "roto",
}


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

    return {
        "health": "ok",
        "color": HEALTH_COLOR["ok"],
        "label": HEALTH_LABEL_ES["ok"],
        "reason": (
            "Ok. Este mapa todavía lee solo el repo (no es productivo): "
            "sin alertas/fallas anexadas, se muestra verde."
        ),
    }


def human_fail_reason(claim: Claim) -> str:
    from okm.humanize import human_claim

    return f"Algo roto según ops: {human_claim(claim)}"


def health_legend() -> list[dict[str, str]]:
    return [
        {
            "kind": "ok",
            "label": "Verde — ok",
            "text": "Sin alertas ni fallas. En demo repo-only, esto es lo normal.",
        },
        {
            "kind": "degraded",
            "label": "Amarillo — alerta",
            "text": "Para cuando anexemos monitoreo: algo a revisar, no crítico.",
        },
        {
            "kind": "failing",
            "label": "Rojo — roto",
            "text": "Reservado para fallas reales de ops/producción.",
        },
    ]
