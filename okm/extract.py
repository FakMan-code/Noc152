"""Deterministic extractors — no LLM, no domain hardcoding."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from okm.models import (
    Claim,
    EpistemicKind,
    Evidence,
    Facet,
    Locator,
    Relation,
)
from okm.store import stable_id, utc_now


@dataclass
class ExtractedBundle:
    evidence: list[Evidence]
    claims: list[Claim]
    relations: list[Relation]
    gaps: list[Claim]


def _excerpt_lines(text: str, start: int, end: int, width: int = 240) -> str:
    lines = text.splitlines()
    chunk = "\n".join(lines[start - 1 : end])
    return chunk[:width]


def make_evidence(
    *,
    source_id: str,
    path: str,
    blob_sha: str,
    start_line: int,
    end_line: int,
    text: str,
) -> Evidence:
    locator = Locator(kind="line_range", start_line=start_line, end_line=end_line)
    eid = stable_id("ev", source_id, path, str(start_line), str(end_line), blob_sha[:12])
    return Evidence(
        evidence_id=eid,
        source_id=source_id,
        path=path,
        blob_sha=blob_sha,
        locator=locator,
        excerpt=_excerpt_lines(text, start_line, end_line),
        retrieved_at=utc_now(),
    )


def extract_from_file(
    *,
    source_id: str,
    path: str,
    blob_sha: str,
    text: str,
    service_id: str | None,
    cfg: dict[str, Any],
) -> ExtractedBundle:
    evidence: list[Evidence] = []
    claims: list[Claim] = []
    relations: list[Relation] = []
    gaps: list[Claim] = []

    extract_cfg = cfg.get("extract", {})
    name = Path(path).name.lower()

    # --- README / identity hints ---
    if name.startswith("readme"):
        lines = text.splitlines()
        title = None
        for i, line in enumerate(lines[:80], start=1):
            m = re.match(r"^#\s+(.+)$", line.strip())
            if m:
                title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                if not title:
                    continue
                ev = make_evidence(
                    source_id=source_id,
                    path=path,
                    blob_sha=blob_sha,
                    start_line=i,
                    end_line=i,
                    text=text,
                )
                evidence.append(ev)
                claims.append(
                    Claim(
                        claim_id=stable_id("cl", service_id or "root", "readme_title", ev.evidence_id),
                        service_id=service_id,
                        facet=Facet.IDENTITY,
                        kind=EpistemicKind.OBSERVED,
                        statement=f"Documented title: {title}",
                        predicate="documented_title",
                        object_value=title,
                        evidence_ids=[ev.evidence_id],
                        producer="extractor.readme",
                    )
                )
                break
        # First prose paragraph (skip HTML / badges)
        para_lines: list[str] = []
        para_start = None
        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("<") or stripped.startswith("[!"):
                if para_lines:
                    break
                continue
            if stripped.startswith("!["):
                continue
            if para_start is None:
                para_start = i
            para_lines.append(stripped)
            if len(" ".join(para_lines)) > 180:
                break
        if para_lines and para_start:
            purpose = " ".join(para_lines)[:240]
            ev = make_evidence(
                source_id=source_id,
                path=path,
                blob_sha=blob_sha,
                start_line=para_start,
                end_line=para_start + len(para_lines) - 1,
                text=text,
            )
            evidence.append(ev)
            claims.append(
                Claim(
                    claim_id=stable_id("cl", service_id or "root", "readme_purpose", ev.evidence_id),
                    service_id=service_id,
                    facet=Facet.IDENTITY,
                    kind=EpistemicKind.INFERRED,
                    statement=f"Likely purpose from README: {purpose}",
                    predicate="likely_purpose",
                    object_value=purpose,
                    evidence_ids=[ev.evidence_id],
                    confidence=0.55,
                    producer="extractor.readme",
                )
            )

    # --- package.json ---
    if name == "package.json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            ev = make_evidence(
                source_id=source_id, path=path, blob_sha=blob_sha, start_line=1, end_line=min(30, text.count("\n") + 1), text=text
            )
            evidence.append(ev)
            pkg_name = data.get("name")
            if pkg_name:
                claims.append(
                    Claim(
                        claim_id=stable_id("cl", service_id or pkg_name, "pkg_name", ev.evidence_id),
                        service_id=service_id,
                        facet=Facet.IDENTITY,
                        kind=EpistemicKind.OBSERVED,
                        statement=f"Package name: {pkg_name}",
                        predicate="package_name",
                        object_value=str(pkg_name),
                        evidence_ids=[ev.evidence_id],
                        producer="extractor.package_json",
                    )
                )
            deps = {}
            if isinstance(data.get("dependencies"), dict):
                deps.update(data["dependencies"])
            if isinstance(data.get("devDependencies"), dict):
                deps.update(data["devDependencies"])
            for dep in sorted(deps)[:40]:
                claims.append(
                    Claim(
                        claim_id=stable_id("cl", service_id or "root", "npm_dep", dep, ev.evidence_id),
                        service_id=service_id,
                        facet=Facet.TOPOLOGY,
                        kind=EpistemicKind.OBSERVED,
                        statement=f"Declares npm dependency: {dep}",
                        predicate="depends_on_package",
                        object_value=dep,
                        evidence_ids=[ev.evidence_id],
                        producer="extractor.package_json",
                    )
                )
                if service_id:
                    relations.append(
                        Relation(
                            relation_id=stable_id("rel", service_id, "npm", dep),
                            kind="depends_on_package",
                            from_service_id=service_id,
                            to_ref=f"npm:{dep}",
                            epistemic=EpistemicKind.OBSERVED,
                            evidence_ids=[ev.evidence_id],
                        )
                    )

    # --- pyproject / requirements ---
    if name == "pyproject.toml":
        ev = make_evidence(
            source_id=source_id, path=path, blob_sha=blob_sha, start_line=1, end_line=min(40, text.count("\n") + 1), text=text
        )
        evidence.append(ev)
        m = re.search(r'(?m)^name\s*=\s*["\']([^"\']+)["\']', text)
        if m:
            claims.append(
                Claim(
                    claim_id=stable_id("cl", service_id or m.group(1), "py_name", ev.evidence_id),
                    service_id=service_id,
                    facet=Facet.IDENTITY,
                    kind=EpistemicKind.OBSERVED,
                    statement=f"Python project name: {m.group(1)}",
                    predicate="package_name",
                    object_value=m.group(1),
                    evidence_ids=[ev.evidence_id],
                    producer="extractor.pyproject",
                )
            )
        # Prefer explicit project.dependencies / optional-dependencies blocks only
        dep_block = re.search(
            r"(?ms)^dependencies\s*=\s*\[(.*?)\]",
            text,
        )
        if dep_block:
            for dep in re.findall(r'["\']([A-Za-z0-9_.-][A-Za-z0-9_.\-]*)', dep_block.group(1)):
                claims.append(
                    Claim(
                        claim_id=stable_id("cl", service_id or "root", "py_dep", dep, path),
                        service_id=service_id,
                        facet=Facet.TOPOLOGY,
                        kind=EpistemicKind.OBSERVED,
                        statement=f"Declares Python dependency: {dep}",
                        predicate="depends_on_package",
                        object_value=dep,
                        evidence_ids=[ev.evidence_id],
                        producer="extractor.pyproject",
                    )
                )
                if service_id:
                    relations.append(
                        Relation(
                            relation_id=stable_id("rel", service_id, "pip", dep),
                            kind="depends_on_package",
                            from_service_id=service_id,
                            to_ref=f"pip:{dep}",
                            epistemic=EpistemicKind.OBSERVED,
                            evidence_ids=[ev.evidence_id],
                        )
                    )

    if name == "requirements.txt":
        for i, line in enumerate(text.splitlines(), start=1):
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            dep = re.split(r"[<>=!~\s\[]", raw, maxsplit=1)[0].strip()
            if not dep or dep in {"-e", ".", "./"} or dep.startswith("-"):
                continue
            ev = make_evidence(
                source_id=source_id, path=path, blob_sha=blob_sha, start_line=i, end_line=i, text=text
            )
            evidence.append(ev)
            claims.append(
                Claim(
                    claim_id=stable_id("cl", service_id or "root", "req", dep, str(i)),
                    service_id=service_id,
                    facet=Facet.TOPOLOGY,
                    kind=EpistemicKind.OBSERVED,
                    statement=f"Declares Python requirement: {dep}",
                    predicate="depends_on_package",
                    object_value=dep,
                    evidence_ids=[ev.evidence_id],
                    producer="extractor.requirements",
                )
            )
            if service_id:
                relations.append(
                    Relation(
                        relation_id=stable_id("rel", service_id, "pip", dep),
                        kind="depends_on_package",
                        from_service_id=service_id,
                        to_ref=f"pip:{dep}",
                        epistemic=EpistemicKind.OBSERVED,
                        evidence_ids=[ev.evidence_id],
                    )
                )

    # --- go.mod ---
    if name == "go.mod":
        m = re.search(r"(?m)^module\s+(\S+)", text)
        if m:
            ev = make_evidence(
                source_id=source_id, path=path, blob_sha=blob_sha, start_line=1, end_line=1, text=text
            )
            evidence.append(ev)
            claims.append(
                Claim(
                    claim_id=stable_id("cl", service_id or m.group(1), "go_module", ev.evidence_id),
                    service_id=service_id,
                    facet=Facet.IDENTITY,
                    kind=EpistemicKind.OBSERVED,
                    statement=f"Go module: {m.group(1)}",
                    predicate="module_path",
                    object_value=m.group(1),
                    evidence_ids=[ev.evidence_id],
                    producer="extractor.go_mod",
                )
            )

    # --- Dockerfile runtime hints ---
    if name.startswith("dockerfile"):
        for i, line in enumerate(text.splitlines(), start=1):
            m = re.match(r"(?i)^\s*FROM\s+(\S+)", line)
            if m:
                ev = make_evidence(
                    source_id=source_id, path=path, blob_sha=blob_sha, start_line=i, end_line=i, text=text
                )
                evidence.append(ev)
                claims.append(
                    Claim(
                        claim_id=stable_id("cl", service_id or "root", "docker_from", m.group(1), str(i)),
                        service_id=service_id,
                        facet=Facet.RUNTIME,
                        kind=EpistemicKind.OBSERVED,
                        statement=f"Container base image: {m.group(1)}",
                        predicate="container_base_image",
                        object_value=m.group(1),
                        evidence_ids=[ev.evidence_id],
                        producer="extractor.dockerfile",
                    )
                )
            m = re.match(r"(?i)^\s*EXPOSE\s+(.+)$", line)
            if m:
                ev = make_evidence(
                    source_id=source_id, path=path, blob_sha=blob_sha, start_line=i, end_line=i, text=text
                )
                evidence.append(ev)
                claims.append(
                    Claim(
                        claim_id=stable_id("cl", service_id or "root", "expose", m.group(1), str(i)),
                        service_id=service_id,
                        facet=Facet.RUNTIME,
                        kind=EpistemicKind.OBSERVED,
                        statement=f"Exposes port(s): {m.group(1).strip()}",
                        predicate="exposes_port",
                        object_value=m.group(1).strip(),
                        evidence_ids=[ev.evidence_id],
                        producer="extractor.dockerfile",
                    )
                )

    # --- HTTP URLs (topology / external) ---
    # Cap noise: only scan config/manifest-ish paths, max N per file
    url_scan = path.endswith((".md", ".yml", ".yaml", ".toml", ".json", ".env.example", ".ini", ".cfg")) or name in {
        "dockerfile",
        "makefile",
        "procfile",
    }
    if url_scan:
        http_re = re.compile(extract_cfg.get("http_url_regex", r"https?://[^\s\"'<>]+"))
        found_urls = 0
        for i, line in enumerate(text.splitlines(), start=1):
            if found_urls >= 15:
                break
            for url in http_re.findall(line):
                if found_urls >= 15:
                    break
                if any(x in url for x in ("img.shields.io", "travis-ci", "badge", "github.com/", "git+")):
                    continue
                ev = make_evidence(
                    source_id=source_id, path=path, blob_sha=blob_sha, start_line=i, end_line=i, text=text
                )
                evidence.append(ev)
                claims.append(
                    Claim(
                        claim_id=stable_id("cl", service_id or "root", "url", url[:80], path, str(i)),
                        service_id=service_id,
                        facet=Facet.TOPOLOGY,
                        kind=EpistemicKind.OBSERVED,
                        statement=f"References URL: {url}",
                        predicate="references_url",
                        object_value=url,
                        evidence_ids=[ev.evidence_id],
                        producer="extractor.http_url",
                    )
                )
                found_urls += 1

    # --- Python imports (topology) ---
    if path.endswith(".py"):
        py_re = re.compile(extract_cfg.get("python_import_regex", r"^\s*(?:from\s+(\S+)\s+import|import\s+(\S+))"))
        import_count = 0
        for i, line in enumerate(text.splitlines(), start=1):
            if import_count >= 30:
                break
            m = py_re.match(line)
            if not m:
                continue
            mod = (m.group(1) or m.group(2) or "").split(".")[0].split(",")[0].strip()
            if not mod or mod.startswith(".") or mod in {"__future__", "typing", "typing_extensions"}:
                continue
            ev = make_evidence(
                source_id=source_id, path=path, blob_sha=blob_sha, start_line=i, end_line=i, text=text
            )
            evidence.append(ev)
            claims.append(
                Claim(
                    claim_id=stable_id("cl", service_id or "root", "pyimp", mod),
                    service_id=service_id,
                    facet=Facet.TOPOLOGY,
                    kind=EpistemicKind.OBSERVED,
                    statement=f"Python import: {mod}",
                    predicate="imports_module",
                    object_value=mod,
                    evidence_ids=[ev.evidence_id],
                    producer="extractor.python_import",
                )
            )
            import_count += 1

    return ExtractedBundle(evidence=evidence, claims=claims, relations=relations, gaps=gaps)
