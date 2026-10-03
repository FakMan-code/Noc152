"""Deterministic Q&A over an expediente — no invented facts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from okm.humanize import human_claim, humanize_ask_answer
from okm.models import Claim, EpistemicKind, Facet, Service
from okm.store import ExpedienteStore

_TOKEN_RE = re.compile(r"[a-z0-9_]{2,}", re.IGNORECASE)

# Spanish + English operator cues → facet bias
_FACET_CUES: dict[Facet, tuple[str, ...]] = {
    Facet.IDENTITY: (
        "que",
        "qué",
        "quien",
        "quién",
        "what",
        "who",
        "identity",
        "identidad",
        "purpose",
        "proposito",
        "propósito",
        "nombre",
        "name",
        "servicio",
        "service",
        "hace",
        "summary",
        "resumen",
    ),
    Facet.TOPOLOGY: (
        "depend",
        "depende",
        "dependencia",
        "topology",
        "topologia",
        "topología",
        "import",
        "paquete",
        "package",
        "relation",
        "relacion",
        "relación",
        "toca",
        "conecta",
        "upstream",
        "downstream",
    ),
    Facet.RUNTIME: (
        "runtime",
        "puerto",
        "port",
        "docker",
        "container",
        "contenedor",
        "deploy",
        "imagen",
        "image",
        "env",
        "ambiente",
    ),
    Facet.SIGNALS: (
        "signal",
        "senal",
        "señal",
        "monitor",
        "alerta",
        "alert",
        "metric",
        "metrica",
        "métrica",
        "log",
        "logs",
        "datadog",
        "observab",
    ),
    Facet.FAILURE: (
        "fail",
        "falla",
        "error",
        "incident",
        "incidente",
        "outage",
        "caida",
        "caída",
        "runbook",
        "recovery",
    ),
}

_GAP_CUES = ("gap", "gaps", "hueco", "huecos", "cobertura", "coverage", "faltante", "missing")

_KIND_WEIGHT = {
    EpistemicKind.OBSERVED: 3.0,
    EpistemicKind.INFERRED: 1.5,
    EpistemicKind.GAP: 1.0,
}

_STOP = {
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
    "de",
    "del",
    "al",
    "en",
    "y",
    "o",
    "a",
    "es",
    "son",
    "que",
    "qué",
    "como",
    "cómo",
    "cual",
    "cuál",
    "para",
    "por",
    "con",
    "se",
    "su",
    "sus",
    "the",
    "a",
    "an",
    "of",
    "and",
    "or",
    "is",
    "are",
    "what",
    "how",
    "which",
    "does",
    "do",
    "it",
    "this",
    "that",
    "tiene",
    "tienen",
    "hay",
    "sobre",
    "me",
    "dime",
    "explica",
    "este",
    "esta",
    "esto",
    "these",
    "those",
}


@dataclass(frozen=True)
class RankedClaim:
    claim: Claim
    score: float


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOP]


def detect_facets(question: str) -> set[Facet]:
    q = question.lower()
    hits: set[Facet] = set()
    for facet, cues in _FACET_CUES.items():
        if any(cue in q for cue in cues):
            hits.add(facet)
    return hits


def score_claim(claim: Claim, tokens: list[str], facet_bias: set[Facet]) -> float:
    hay = " ".join(
        filter(
            None,
            [
                claim.statement,
                claim.predicate,
                claim.object_value or "",
                claim.facet.value,
                claim.kind.value,
                claim.gap_reason or "",
            ],
        )
    ).lower()
    hits = sum(1 for t in tokens if t in hay) if tokens else 0
    in_bias = bool(facet_bias and claim.facet in facet_bias)

    if hits == 0:
        if in_bias:
            # Facet-shaped question ("qué es…", "dependencias…") with no lexical hit:
            # still surface claims from that facet instead of empty answers.
            if claim.kind == EpistemicKind.GAP:
                base = 0.45
            elif claim.predicate in {"likely_purpose", "package_name", "documented_title", "facet_uncovered", "facet_incomplete"}:
                base = 0.55
            else:
                base = 0.3
        elif not tokens:
            base = 0.12 if claim.kind != EpistemicKind.GAP else 0.05
        else:
            return 0.0
    else:
        base = hits / max(len(tokens), 1)

    score = base * _KIND_WEIGHT[claim.kind]
    if in_bias:
        score *= 1.8
    if claim.evidence_ids:
        score += 0.15
    if claim.kind == EpistemicKind.GAP and in_bias:
        score = max(score, 0.9)
    return score


def wants_gaps(question: str) -> bool:
    q = question.lower()
    return any(cue in q for cue in _GAP_CUES)


def rank_claims(
    claims: list[Claim],
    question: str,
    *,
    limit: int = 8,
) -> list[RankedClaim]:
    tokens = tokenize(question)
    facet_bias = detect_facets(question)
    gap_focus = wants_gaps(question)
    ranked: list[RankedClaim] = []
    for claim in claims:
        s = score_claim(claim, tokens, facet_bias)
        if gap_focus and claim.kind == EpistemicKind.GAP:
            s = max(s, 2.5)
        if s > 0:
            ranked.append(RankedClaim(claim=claim, score=s))
    ranked.sort(key=lambda r: (-r.score, r.claim.kind.value, r.claim.facet.value))
    return ranked[:limit]


def export_payload(store: ExpedienteStore, service: Service) -> dict[str, Any]:
    claims = store.claims_for(service.service_id)
    evidence_out: list[dict[str, Any]] = []
    seen_ev: set[str] = set()
    for c in claims:
        for eid in c.evidence_ids[:1]:
            if eid in seen_ev:
                continue
            ev = store.get_evidence(eid)
            if not ev:
                continue
            seen_ev.add(eid)
            evidence_out.append(
                {
                    "id": ev.evidence_id,
                    "path": ev.path,
                    "locator": ev.locator.to_json(),
                    "excerpt": ev.excerpt,
                    "ref": ev.openable_ref(),
                }
            )
    return {
        "service": {
            "id": service.service_id,
            "name": service.name,
            "aliases": service.aliases,
            "root_path": service.root_path,
            "summary": service.summary,
        },
        "claims": [
            {
                "id": c.claim_id,
                "facet": c.facet.value,
                "kind": c.kind.value,
                "statement": c.statement,
                "predicate": c.predicate,
                "object": c.object_value,
                "evidence_ids": c.evidence_ids,
                "confidence": c.confidence,
                "gap_reason": c.gap_reason,
                "producer": c.producer,
            }
            for c in claims
        ],
        "relations": [
            {
                "id": r.relation_id,
                "kind": r.kind,
                "to": r.to_ref,
                "epistemic": r.epistemic.value,
            }
            for r in store.relations_for(service.service_id)
        ],
        "coverage": store.coverage_for(service.service_id),
        "evidence": evidence_out,
    }


def brief_for_ui(store: ExpedienteStore, service: Service) -> dict[str, Any]:
    """Compact expediente shaped for accordion UI."""
    claims = store.claims_for(service.service_id)
    relations = store.relations_for(service.service_id)
    coverage = store.coverage_for(service.service_id)

    by_facet: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for facet in Facet:
        by_facet[facet.value] = {"observed": [], "inferred": [], "gap": []}

    noisy = {"imports_module", "references_url"}
    noisy_cap = 8
    noisy_count = 0

    for c in claims:
        if c.predicate in noisy:
            if noisy_count >= noisy_cap:
                continue
            noisy_count += 1
        item: dict[str, Any] = {
            "id": c.claim_id,
            "statement": c.statement,
            "predicate": c.predicate,
            "object": c.object_value,
            "kind": c.kind.value,
            "gap_reason": c.gap_reason,
            "evidence": [],
        }
        for eid in c.evidence_ids[:1]:
            ev = store.get_evidence(eid)
            if ev:
                item["evidence"].append(
                    {
                        "id": ev.evidence_id,
                        "ref": ev.openable_ref(),
                        "path": ev.path,
                        "excerpt": ev.excerpt[:280],
                    }
                )
        bucket = by_facet[c.facet.value][c.kind.value]
        if len(bucket) < 14:
            bucket.append(item)

    pkg_rels = [
        {"kind": r.kind, "to": r.to_ref, "epistemic": r.epistemic.value}
        for r in relations
        if r.kind == "depends_on_package"
    ][:16]

    return {
        "service": {
            "id": service.service_id,
            "name": service.name,
            "aliases": service.aliases,
            "root_path": service.root_path,
            "summary": service.summary,
        },
        "coverage": coverage,
        "facets": by_facet,
        "relations": pkg_rels,
        "totals": {
            "claims": len(claims),
            "relations": len(relations),
            "observed": sum(1 for c in claims if c.kind == EpistemicKind.OBSERVED),
            "inferred": sum(1 for c in claims if c.kind == EpistemicKind.INFERRED),
            "gap": sum(1 for c in claims if c.kind == EpistemicKind.GAP),
        },
    }


def answer_question(
    store: ExpedienteStore,
    question: str,
    *,
    service_name: str | None = None,
) -> dict[str, Any]:
    q = (question or "").strip()
    if not q:
        return {
            "ok": False,
            "answer": "Escribí una pregunta sobre el servicio o el expediente.",
            "hits": [],
            "facets": [],
            "service": None,
        }

    services = store.list_services()
    if not services:
        return {
            "ok": False,
            "answer": "No hay servicios en el workspace. Corré ingest primero.",
            "hits": [],
            "facets": [],
            "service": None,
        }

    svc: Service | None = None
    if service_name:
        svc = store.get_service(service_name)
    if svc is None and len(services) == 1:
        svc = services[0]
    if svc is None:
        # Try to resolve a service name mentioned in the question
        q_low = q.lower()
        for candidate in services:
            names = [candidate.name.lower(), *([a.lower() for a in candidate.aliases])]
            if any(n and n in q_low for n in names):
                svc = candidate
                break
    if svc is None:
        names = ", ".join(s.name for s in services)
        return {
            "ok": False,
            "answer": f"Indicá el servicio. Disponibles: {names}",
            "hits": [],
            "facets": [],
            "service": None,
        }

    claims = store.claims_for(svc.service_id)
    ranked = rank_claims(claims, q, limit=8)
    facets = sorted(f.value for f in detect_facets(q))

    hits: list[dict[str, Any]] = []
    for item in ranked:
        c = item.claim
        evidence = []
        for eid in c.evidence_ids[:2]:
            ev = store.get_evidence(eid)
            if ev:
                evidence.append(
                    {
                        "id": ev.evidence_id,
                        "ref": ev.openable_ref(),
                        "path": ev.path,
                        "excerpt": store.open_excerpt(ev.evidence_id) or ev.excerpt,
                    }
                )
        hits.append(
            {
                "score": round(item.score, 3),
                "facet": c.facet.value,
                "kind": c.kind.value,
                "statement": c.statement,
                "statement_es": human_claim(c),
                "predicate": c.predicate,
                "gap_reason": c.gap_reason,
                "evidence": evidence,
            }
        )

    answer = humanize_ask_answer(service_name=svc.name, hits=hits, question=q)
    return {
        "ok": True,
        "answer": answer,
        "hits": hits,
        "facets": facets,
        "service": {"id": svc.service_id, "name": svc.name, "summary": svc.summary},
    }
