"""Noc152 agent — Cursor-like answers grounded in the expediente + mapa Archify.

Uses local Ollama (qwen2.5) when available; falls back to structured retrieval.
Never invents evidence: the model only sees dossier snippets we attach.
Código de nodos lógicos: lectura local vía node_sources (auditada). MCP remoto = fase 2.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from okm.archify_adapter import find_archify_spec, load_archify_spec
from okm.ask import detect_facets, rank_claims
from okm.audit import write_ask_audit
from okm.humanize import (
    facet_label,
    human_claim,
    human_summary,
    humanize_ask_answer,
    kind_label,
)
from okm.models import Service
from okm.node_sources import (
    export_payload,
    format_sources_block,
    read_node_sources,
    short_code_answer,
    wants_source_code,
)
from okm.store import ExpedienteStore

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_MODEL = "qwen2.5:7b"
TIMEOUT_S = 90

_ARCHIFY_ALIASES = frozenset({"__archify__", "archify", ""})

SYSTEM = """Sos el agente de Noc152:
claro, directo, en español rioplatense neutro, sin relleno corporativo.
Leés el mapa 3D, el expediente y —si viene— CÓDIGO FUENTE real del repo.

Reglas duras:
1) Solo podés afirmar lo que esté en el DOSSIER. Si no está, decí que es un hueco.
2) No inventes archivos, métricas, alertas ni runbooks.
3) Si hay MAPA ARCHIFY, priorizalo para preguntas sobre nodos, enlaces o el dibujo.
4) Si hay NODO EN FOCO, empezá por ese nodo (qué es, con quién conecta, fuentes).
5) Si hay bloque CÓDIGO FUENTE DEL NODO, ese es el código real: citá paths y pegá
   fragmentos relevantes. NO digas que no hay código de Combinado si ese bloque existe.
6) Cuando cites un hallazgo, mencioná path:líneas si existe.
7) Explicá en criollo qué significa para un operador NOC.
8) Si el dossier dice que algo es librería/cliente (no servidor), no lo trates como app desplegada.

Formato de respuesta (markdown liviano, sin tablas enormes):
**Qué es** — una o dos frases
**En el mapa** — nodos/enlaces relevantes
**Evidencia** — refs o código (paths)
**Huecos** — qué no está
**Siguiente** — qué mirar o preguntar después
"""


def _resolve_service(
    store: ExpedienteStore,
    service_name: str | None,
    question: str,
) -> Service | None:
    services = store.list_services()
    if not services:
        return None
    name = (service_name or "").strip()
    if name and name.lower() not in _ARCHIFY_ALIASES:
        svc = store.get_service(name)
        if svc:
            return svc
    if len(services) == 1:
        return services[0]
    q_low = question.lower()
    for candidate in services:
        names = [candidate.name.lower(), *[a.lower() for a in candidate.aliases]]
        if any(n and n in q_low for n in names):
            return candidate
    return services[0] if services else None


def _match_component(
    components: list[dict[str, Any]],
    focus_node: str | None,
    question: str,
) -> dict[str, Any] | None:
    if focus_node:
        fid = focus_node.strip().lower()
        for comp in components:
            cid = str(comp.get("id") or "").lower()
            label = str(comp.get("label") or "").lower()
            if fid in {cid, label} or fid == cid:
                return comp
        for comp in components:
            if str(comp.get("id") or "").lower() == fid:
                return comp
    q = question.lower()
    scored: list[tuple[int, dict[str, Any]]] = []
    for comp in components:
        cid = str(comp.get("id") or "").lower()
        label = str(comp.get("label") or "").lower()
        sub = str(comp.get("sublabel") or "").lower()
        score = 0
        if cid and cid in q:
            score += 5
        if label and label in q:
            score += 4
        if sub and sub in q:
            score += 2
        for token in (cid, label):
            if token and len(token) >= 3 and token in q:
                score += 1
        if score:
            scored.append((score, comp))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


def _archify_map_block(
    store: ExpedienteStore,
    question: str,
    focus_node: str | None,
) -> str:
    spec_path = find_archify_spec(store.workspace)
    if not spec_path:
        return ""
    try:
        spec = load_archify_spec(spec_path)
    except (OSError, json.JSONDecodeError, ValueError, KeyError):
        return ""

    meta = spec.get("meta") or {}
    components = list(spec.get("components") or [])
    connections = list(spec.get("connections") or [])
    boundaries = list(spec.get("boundaries") or [])
    cards = list(spec.get("cards") or [])
    views = list((meta.get("views") or []))
    repo = meta.get("repository") or {}

    by_id = {str(c.get("id")): c for c in components if c.get("id")}
    focus = _match_component(components, focus_node, question)

    lines = [
        "MAPA ARCHIFY (fuente de verdad del dibujo 3D):",
        f"Título: {meta.get('title') or spec_path.name}",
        f"Spec: {spec_path.name}",
    ]
    if repo.get("url"):
        lines.append(f"Repo: {repo.get('url')} @ {repo.get('revision') or '?'}")
    lines.append(f"Componentes: {len(components)} · Relaciones: {len(connections)}")
    lines.append("")
    lines.append("NODOS:")
    for comp in components:
        cid = comp.get("id")
        label = comp.get("label") or cid
        ctype = comp.get("type") or "?"
        sub = comp.get("sublabel") or ""
        tag = comp.get("tag") or ""
        srcs = []
        for src in list(comp.get("sources") or [])[:3]:
            path = src.get("path", "")
            line = src.get("line")
            ref = f"{path}:L{line}" if line else path
            if src.get("label"):
                ref = f"{src['label']} ({ref})"
            srcs.append(ref)
        bit = f"- {cid} | {label} | tipo={ctype}"
        if sub:
            bit += f" | {sub}"
        if tag:
            bit += f" | tag={tag}"
        if srcs:
            bit += f" | fuentes: {', '.join(srcs)}"
        lines.append(bit)

    lines.append("")
    lines.append("ENLACES:")
    for conn in connections:
        frm = conn.get("from")
        to = conn.get("to")
        lab = conn.get("label") or ""
        var = conn.get("variant") or "default"
        piece = f"- {frm} → {to}"
        if lab:
            piece += f" ({lab})"
        if var != "default":
            piece += f" [{var}]"
        lines.append(piece)

    if boundaries:
        lines.append("")
        lines.append("BOUNDARIES:")
        for b in boundaries:
            wraps = ", ".join(str(x) for x in (b.get("wraps") or []))
            lines.append(f"- {b.get('kind')}: {b.get('label')} ⊃ {wraps}")

    if views:
        lines.append("")
        lines.append("VISTAS:")
        for v in views:
            focus_ids = ", ".join(str(x) for x in (v.get("focus") or []))
            note = v.get("note") or ""
            lines.append(f"- {v.get('id')}: {v.get('label')} · focus=[{focus_ids}] · {note}")

    if cards:
        lines.append("")
        lines.append("CARDS:")
        for card in cards[:12]:
            lines.append(
                f"- {card.get('id') or '?'}: {card.get('title') or card.get('label') or ''} "
                f"— {(card.get('body') or card.get('text') or '')[:220]}"
            )

    if focus:
        cid = str(focus.get("id"))
        lines.append("")
        lines.append("NODO EN FOCO (el operador lo tiene seleccionado o lo nombró):")
        lines.append(
            f"- id={cid} label={focus.get('label')} tipo={focus.get('type')} "
            f"sub={focus.get('sublabel') or ''} tag={focus.get('tag') or ''}"
        )
        for src in list(focus.get("sources") or [])[:5]:
            path = src.get("path", "")
            line = src.get("line")
            ref = f"{path}:L{line}" if line else path
            lines.append(f"  fuente: {src.get('label') or path} — {ref}")
        related = []
        for conn in connections:
            if conn.get("from") == cid or conn.get("to") == cid:
                other = conn.get("to") if conn.get("from") == cid else conn.get("from")
                other_c = by_id.get(str(other), {})
                related.append(
                    f"{conn.get('from')}→{conn.get('to')} "
                    f"({conn.get('label') or 'enlace'}) "
                    f"[{other_c.get('label') or other}]"
                )
        if related:
            lines.append("  conexiones:")
            lines.extend(f"  - {r}" for r in related)

    return "\n".join(lines)


def build_dossier(
    store: ExpedienteStore,
    service: Service,
    question: str,
    *,
    limit: int = 10,
    focus_node: str | None = None,
    source_files: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    claims = store.claims_for(service.service_id)
    ranked = rank_claims(claims, question, limit=limit)
    hits: list[dict[str, Any]] = []
    map_block = _archify_map_block(store, question, focus_node)
    lines = [
        f"Servicio: {service.name}",
        f"Resumen: {human_summary(service)}",
        f"Pregunta del operador: {question}",
        "",
    ]
    if focus_node:
        lines.append(f"NODO EN FOCO: {focus_node}")
        lines.append("")
    src_block = format_sources_block(source_files or [])
    if src_block:
        lines.append(src_block)
        lines.append("")
    if map_block:
        lines.append(map_block)
        lines.append("")
    lines.append("HALLAZGOS DEL EXPEDIENTE:")
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
    focus_node: str | None = None,
    use_llm: bool = True,
    model: str = DEFAULT_MODEL,
    depth: str = "quick",
) -> dict[str, Any]:
    q = (question or "").strip()
    ask_depth = "deep" if str(depth or "").lower() == "deep" else "quick"
    if not q:
        return {
            "ok": False,
            "answer": "Escribí una pregunta sobre el mapa o el expediente.",
            "hits": [],
            "facets": [],
            "service": None,
            "mode": "empty",
        }

    services = store.list_services()
    if not services and not find_archify_spec(store.workspace):
        return {
            "ok": False,
            "answer": "No hay servicios en el workspace. Corré ingest primero.",
            "hits": [],
            "facets": [],
            "service": None,
            "mode": "empty",
        }

    source_files = read_node_sources(
        store, focus_node=focus_node, question=q, depth=ask_depth
    )
    source_paths = [f["path"] for f in source_files]

    # Pedido de código → resumen corto + export (UI copia/descarga archivo completo).
    if wants_source_code(q) and (focus_node or source_files):
        full_files = read_node_sources(
            store,
            focus_node=focus_node,
            question=q,
            for_dossier=False,
            depth=ask_depth,
        )
        if not full_files and focus_node:
            full_files = read_node_sources(
                store,
                focus_node=focus_node,
                question=focus_node,
                for_dossier=False,
                depth=ask_depth,
            )
        source_paths = [f["path"] for f in full_files]
        answer = short_code_answer(full_files, focus_node)
        exp = export_payload(full_files, focus_node)
        payload = {
            "ok": True,
            "answer": answer,
            "hits": [],
            "facets": ["code"],
            "service": None,
            "mode": "source",
            "model": None,
            "focus_node": focus_node,
            "sources_opened": source_paths,
            "export": exp,
            "audit": "workspace/audit/ask/",
        }
        write_ask_audit(
            store.workspace,
            question=q,
            service=service_name,
            focus_node=focus_node,
            mode="source",
            model=None,
            answer=answer,
            ok=True,
            sources_opened=source_paths,
            extra={"export_label": exp.get("label"), "primary": exp.get("primary")},
        )
        return payload

    svc = _resolve_service(store, service_name, q)
    if svc is None:
        # Archify-only workspace: still answer from the map.
        map_block = _archify_map_block(store, q, focus_node)
        dossier = map_block or ""
        if source_files:
            dossier = format_sources_block(source_files) + "\n\n" + dossier
        if dossier and use_llm:
            answer = _ollama_chat(dossier + f"\n\nPregunta:\n{q}", q, model=model)
            if answer:
                write_ask_audit(
                    store.workspace,
                    question=q,
                    service=service_name,
                    focus_node=focus_node,
                    mode="agent",
                    model=model,
                    answer=answer,
                    ok=True,
                    sources_opened=source_paths,
                )
                return {
                    "ok": True,
                    "answer": answer,
                    "hits": [],
                    "facets": [],
                    "service": None,
                    "mode": "agent",
                    "model": model,
                    "focus_node": focus_node,
                    "sources_opened": source_paths,
                }
        names = ", ".join(s.name for s in services) if services else "(ninguno)"
        fail = {
            "ok": False,
            "answer": f"Indicá el servicio. Disponibles: {names}",
            "hits": [],
            "facets": [],
            "service": None,
            "mode": "empty",
        }
        write_ask_audit(
            store.workspace,
            question=q,
            service=service_name,
            focus_node=focus_node,
            mode="empty",
            model=None,
            answer=fail["answer"],
            ok=False,
            sources_opened=source_paths,
        )
        return fail

    hits, dossier = build_dossier(
        store, svc, q, focus_node=focus_node, source_files=source_files
    )
    facets = sorted(f.value for f in detect_facets(q))
    mode = "retrieval"
    answer: str | None = None

    if use_llm:
        answer = _ollama_chat(dossier, q, model=model)
        if answer:
            mode = "agent"

    if not answer:
        answer = humanize_ask_answer(service_name=svc.name, hits=hits, question=q)
        has_map = "MAPA ARCHIFY" in dossier
        answer = (
            f"**Qué es**\n{q}\n\n"
            f"**Lo que encontré**\n{answer}\n\n"
            "**Nota**\n"
            + (
                "Respondí con el mapa Archify + expediente local "
                if has_map
                else "Respondí con el expediente local "
            )
            + "(Ollama no contestó a tiempo o no está disponible)."
        )
        mode = "retrieval"

    write_ask_audit(
        store.workspace,
        question=q,
        service=svc.name,
        focus_node=focus_node,
        mode=mode,
        model=model if mode == "agent" else None,
        answer=answer,
        ok=True,
        sources_opened=source_paths,
    )

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
        "focus_node": focus_node,
        "sources_opened": source_paths,
        "audit": "workspace/audit/ask/",
    }
