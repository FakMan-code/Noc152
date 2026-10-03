"""End-to-end build of an operational expediente from a generic source."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from okm.config import load_config
from okm.extract import extract_from_file
from okm.ingest import materialize_source, walk_source
from okm.models import Claim, EpistemicKind, Facet, RunReceipt
from okm.resolve import assign_service, discover_services
from okm.store import ExpedienteStore, stable_id, utc_now


FACET_EXPECTED = {
    Facet.IDENTITY: ["documented_title", "package_name", "module_path", "likely_purpose"],
    Facet.TOPOLOGY: ["depends_on_package", "imports_module", "references_url"],
    Facet.RUNTIME: ["container_base_image", "exposes_port"],
    Facet.SIGNALS: [],  # not available from repo-only demo
    Facet.FAILURE: [],  # not available from repo-only demo
}


def build_expediente(
    source: str,
    workspace: Path,
    *,
    config_path: Path | None = None,
    keep_clone: bool = True,
) -> ExpedienteStore:
    cfg = load_config(config_path)
    store_cfg = cfg.get("store", {})
    store = ExpedienteStore(
        workspace,
        db_filename=store_cfg.get("db_filename", "expediente.sqlite3"),
        blobs_dirname=store_cfg.get("blobs_dirname", "blobs"),
    )

    cache = workspace / "source_cache"
    root, source_uri, _ = materialize_source(source, cache)
    run_id = store.start_run(source_uri)
    receipt = RunReceipt(run_id=run_id, source_uri=source_uri, started_at=utc_now())

    ingest_cfg = cfg.get("ingest", {})
    text_exts = {e.lower() for e in ingest_cfg.get("text_extensions", [])}
    special = set(ingest_cfg.get("special_filenames", []))
    ignore_dirs = set(ingest_cfg.get("ignore_dirs", {}).get("names", []))
    ignore_globs = list(ingest_cfg.get("ignore_globs", {}).get("patterns", []))
    max_bytes = int(ingest_cfg.get("max_file_bytes", 1_048_576))
    max_files = int(ingest_cfg.get("max_files", 8_000))

    files = list(
        walk_source(
            root,
            text_exts=text_exts,
            special_names=special,
            ignore_dirs=ignore_dirs,
            ignore_globs=ignore_globs,
            max_file_bytes=max_bytes,
            max_files=max_files,
        )
    )
    receipt.files_seen = len(files)

    services = discover_services(
        [f.relative_path for f in files],
        source_uri=source_uri,
        cfg=cfg,
    )
    for svc in services:
        store.upsert_service(svc)

    source_id = stable_id("src", source_uri)
    claims_n = 0
    gaps_n = 0
    predicates_seen: dict[str, set[str]] = {s.service_id: set() for s in services}

    for sf in files:
        try:
            data = sf.absolute_path.read_bytes()
        except OSError as exc:
            receipt.errors.append(f"{sf.relative_path}: {exc}")
            receipt.files_skipped += 1
            continue

        # Skip obvious binaries that slipped through
        if b"\x00" in data[:2048]:
            receipt.files_skipped += 1
            continue

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = data.decode("latin-1")
            except Exception as exc:  # noqa: BLE001
                receipt.errors.append(f"{sf.relative_path}: decode {exc}")
                receipt.files_skipped += 1
                continue

        blob_sha = store.put_blob(data)
        store.add_document(source_id, sf.relative_path, blob_sha, run_id)
        receipt.files_ingested += 1

        svc = assign_service(sf.relative_path, services)
        sid = svc.service_id if svc else None
        bundle = extract_from_file(
            source_id=source_id,
            path=sf.relative_path,
            blob_sha=blob_sha,
            text=text,
            service_id=sid,
            cfg=cfg,
        )
        for ev in bundle.evidence:
            store.add_evidence(ev)
        for claim in bundle.claims:
            # Enforce: observed must have evidence
            if claim.kind == EpistemicKind.OBSERVED and not claim.evidence_ids:
                claim.kind = EpistemicKind.INFERRED
                claim.confidence = claim.confidence or 0.3
            store.add_claim(claim)
            claims_n += 1
            if sid and claim.predicate:
                predicates_seen.setdefault(sid, set()).add(claim.predicate)
        for rel in bundle.relations:
            store.add_relation(rel)

    # Coverage gaps (generic expectations for a repo-only source)
    for svc in services:
        seen = predicates_seen.get(svc.service_id, set())
        for facet, expected in FACET_EXPECTED.items():
            if not expected:
                gap = Claim(
                    claim_id=stable_id("gap", svc.service_id, facet.value, "source_missing"),
                    service_id=svc.service_id,
                    facet=facet,
                    kind=EpistemicKind.GAP,
                    statement=f"No repository signals for facet '{facet.value}' in this source set",
                    predicate="facet_uncovered",
                    object_value=facet.value,
                    gap_reason="source_not_in_scope",
                    producer="coverage.repo_only",
                )
                store.add_claim(gap)
                gaps_n += 1
                continue
            if not any(p in seen for p in expected):
                gap = Claim(
                    claim_id=stable_id("gap", svc.service_id, facet.value, "missing"),
                    service_id=svc.service_id,
                    facet=facet,
                    kind=EpistemicKind.GAP,
                    statement=f"Missing observed signals for facet '{facet.value}'",
                    predicate="facet_incomplete",
                    object_value=facet.value,
                    gap_reason="not_found_in_source",
                    producer="coverage.scan",
                )
                store.add_claim(gap)
                gaps_n += 1

        # Identity summary from best claims
        svc_claims = store.claims_for(svc.service_id)
        title = next(
            (c.object_value for c in svc_claims if c.predicate in {"documented_title", "package_name", "module_path"} and c.object_value),
            None,
        )
        purpose = next(
            (c.object_value for c in svc_claims if c.predicate == "likely_purpose" and c.object_value),
            None,
        )
        if title or purpose:
            svc.summary = purpose or title
            if title and title not in svc.aliases:
                svc.aliases.append(title)
            store.upsert_service(svc)

    receipt.claims_written = claims_n
    receipt.gaps_written = gaps_n
    receipt.finished_at = utc_now()
    store.finish_run(receipt)
    return store


def format_service_card(store: ExpedienteStore, name_or_id: str) -> str:
    svc = store.get_service(name_or_id)
    if not svc:
        known = ", ".join(s.name for s in store.list_services()) or "(none)"
        return f"Service not found: {name_or_id}\nKnown: {known}"

    claims = store.claims_for(svc.service_id)
    rels = store.relations_for(svc.service_id)
    coverage = store.coverage_for(svc.service_id)

    # Keep the human card readable: cap noisy predicates
    noisy = {"imports_module", "references_url"}
    max_noisy = 12

    lines: list[str] = []
    lines.append(f"Service: {svc.name}")
    lines.append(f"ID: {svc.service_id}")
    lines.append(f"Root: {svc.root_path}")
    if svc.aliases:
        lines.append(f"Aliases: {', '.join(svc.aliases)}")
    if svc.summary:
        lines.append(f"Summary: {svc.summary}")
    lines.append("")

    for kind in (EpistemicKind.OBSERVED, EpistemicKind.INFERRED, EpistemicKind.GAP):
        subset = [c for c in claims if c.kind == kind]
        if not subset:
            continue
        lines.append(kind.value.upper())
        shown = 0
        noisy_shown = 0
        omitted = 0
        for c in subset:
            if c.predicate in noisy:
                if noisy_shown >= max_noisy:
                    omitted += 1
                    continue
                noisy_shown += 1
            if shown >= 50:
                omitted += 1
                continue
            proof = ""
            if c.evidence_ids:
                ev = store.get_evidence(c.evidence_ids[0])
                if ev:
                    proof = f"  [{ev.openable_ref()}]"
            extra = f" ({c.gap_reason})" if c.gap_reason else ""
            lines.append(f"- [{c.facet.value}] {c.statement}{extra}{proof}")
            shown += 1
        if omitted:
            lines.append(f"  ... {omitted} more claims omitted for readability")
        lines.append("")

    if rels:
        lines.append("RELATIONS")
        for r in rels[:30]:
            lines.append(f"- {r.kind} -> {r.to_ref} ({r.epistemic.value})")
        if len(rels) > 30:
            lines.append(f"  ... {len(rels) - 30} more")
        lines.append("")

    lines.append("COVERAGE (counts)")
    for facet, counts in coverage.items():
        lines.append(
            f"- {facet}: observed={counts['observed']} inferred={counts['inferred']} gap={counts['gap']}"
        )
    return "\n".join(lines)
