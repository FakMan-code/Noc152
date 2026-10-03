"""Noc152 agent — Cursor-like answers grounded in the expediente.

Uses local Ollama (qwen2.5) when available; falls back to structured retrieval.
Never invents evidence: the model only sees dossier snippets we attach.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from okm.ask import detect_facets, rank_claims
from okm.humanize import (
    facet_label,
    human_claim,
    human_summary,
    humanize_ask_answer,
    kind_label,
)
from okm.models import Service
from okm.store import ExpedienteStore

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_MODEL = "qwen2.5:7b"
TIMEOUT_S = 90


SYSTEM = """Sos el agente de Noc152, con el estilo de un asistente de Cursor:
claro, directo, en español rioplatense neutro, sin relleno corporativo.

Reglas duras:
1) Solo podés afirmar lo que esté en el DOSSIER. Si no está, decí que es un hueco.
2) No inventes archivos, métricas, alertas ni runbooks.
3) Cuando cites un hallazgo, mencioná la evidencia (path:líneas) si existe.
4) Explicá en criollo qué significa para un operador NOC.
5) HTTPX (si aparece) es una biblioteca cliente HTTP de Python, no una app servidor.

Formato de respuesta (markdown liviano, sin tablas enormes):
**Qué preguntaste** — una línea
**Lo que encontré** — 2 a 5 viñetas humanas
**Evidencia** — refs concretas
**Huecos** — qué no está en el repo
**Siguiente paso** — una sugerencia práctica (otra pregunta o qué mirar en el mapa)
"""


def _resolve_service(
    store: ExpedienteStore,
    service_name: str | None,
    question: str,
) -> Service | None:
    services = store.list_services()
    if not services:
        return None
    if service_name:
        svc = store.get_service(service_name)
        if svc:
            return svc
    if len(services) == 1:
        return services[0]
    q_low = question.lower()
    for candidate in services:
        names = [candidate.name.lower(), *[a.lower() for a in candidate.aliases]]
        if any(n and n in q_low for n in names):
            return candidate
    return None


def build_dossier(
    store: ExpedienteStore,
    service: Service,
    question: str,
    *,
    limit: int = 10,
) -> tuple[list[dict[str, Any]], str]:
    claims = store.claims_for(service.service_id)
    ranked = rank_claims(claims, question, limit=limit)
    hits: list[dict[str, Any]] = []
    lines = [
        f"Servicio: {service.name}",
        f"Resumen: {human_summary(service)}",
        f"Pregunta del operador: {question}",
        "",
        "HALLAZGOS DEL EXPEDIENTE:",
    ]
    for item in ranked:
        c = item.claim
        text_es = human_claim(c)
        evidence = []
        for eid in c.evidence_ids[:2]:
            ev = store.get_evidence(eid)
            if not ev:
                continue
            excerpt = store.open_excerpt(eid) or ev.excerpt
            evidence.append(
                {
                    "id": ev.evidence_id,
                    "ref": ev.openable_ref(),
                    "path": ev.path,
                    "excerpt": (excerpt or "")[:500],
                }
            )
        hits.append(
            {
                "score": round(item.score, 3),
                "facet": c.facet.value,
                "kind": c.kind.value,
                "statement": c.statement,
                "statement_es": text_es,
                "predicate": c.predicate,
                "gap_reason": c.gap_reason,
                "evidence": evidence,
            }
        )
        refs = ", ".join(e["ref"] for e in evidence) or "(sin evidencia abríble)"
        lines.append(
            f"- [{kind_label(c.kind.value)} · {facet_label(c.facet.value)}] "
            f"{text_es} | {refs}"
        )
        for e in evidence[:1]:
            lines.append(f"  excerpt: {e['excerpt'][:220]}")

    if not ranked:
        lines.append("- (ningún hallazgo rankeó para esta pregunta)")

    return hits, "\n".join(lines)


def _ollama_chat(dossier: str, question: str, model: str = DEFAULT_MODEL) -> str | None:
    payload = {
        "model": model,
        "stream": False,
        "options": {"temperature": 0.3},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": f"DOSSIER:\n{dossier}\n\nPregunta:\n{question}",
            },
        ],
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    msg = data.get("message") or {}
    content = (msg.get("content") or "").strip()
    return content or None


def agent_answer(
    store: ExpedienteStore,
    question: str,
    *,
    service_name: str | None = None,
    use_llm: bool = True,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    q = (question or "").strip()
    if not q:
        return {
            "ok": False,
            "answer": "Escribí una pregunta sobre el servicio o el expediente.",
            "hits": [],
            "facets": [],
            "service": None,
            "mode": "empty",
        }

    services = store.list_services()
    if not services:
        return {
            "ok": False,
            "answer": "No hay servicios en el workspace. Corré ingest primero.",
            "hits": [],
            "facets": [],
            "service": None,
            "mode": "empty",
        }

    svc = _resolve_service(store, service_name, q)
    if svc is None:
        names = ", ".join(s.name for s in services)
        return {
            "ok": False,
            "answer": f"Indicá el servicio. Disponibles: {names}",
            "hits": [],
            "facets": [],
            "service": None,
            "mode": "empty",
        }

    hits, dossier = build_dossier(store, svc, q)
    facets = sorted(f.value for f in detect_facets(q))
    mode = "retrieval"
    answer: str | None = None

    if use_llm:
        answer = _ollama_chat(dossier, q, model=model)
        if answer:
            mode = "agent"

    if not answer:
        answer = humanize_ask_answer(service_name=svc.name, hits=hits, question=q)
        # Make fallback feel more agent-like
        answer = (
            f"**Qué preguntaste**\n{q}\n\n"
            f"**Lo que encontré**\n{answer}\n\n"
            "**Nota**\nRespondí con el expediente local "
            "(el modelo Ollama no contestó a tiempo o no está disponible)."
        )
        mode = "retrieval"

    return {
        "ok": True,
        "answer": answer,
        "hits": hits,
        "facets": facets,
        "service": {
            "id": svc.service_id,
            "name": svc.name,
            "summary": human_summary(svc),
        },
        "mode": mode,
        "model": model if mode == "agent" else None,
    }
