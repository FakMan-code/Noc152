"""Content-addressed blob store + SQLite expediente."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from okm.models import (
    Claim,
    EpistemicKind,
    Evidence,
    Facet,
    Locator,
    Relation,
    RunReceipt,
    Service,
)


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  source_uri TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  files_seen INTEGER NOT NULL DEFAULT 0,
  files_ingested INTEGER NOT NULL DEFAULT 0,
  files_skipped INTEGER NOT NULL DEFAULT 0,
  claims_written INTEGER NOT NULL DEFAULT 0,
  gaps_written INTEGER NOT NULL DEFAULT 0,
  errors_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS blobs (
  sha256 TEXT PRIMARY KEY,
  size_bytes INTEGER NOT NULL,
  stored_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  path TEXT NOT NULL,
  blob_sha TEXT NOT NULL REFERENCES blobs(sha256),
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  UNIQUE(source_id, path, blob_sha)
);

CREATE TABLE IF NOT EXISTS evidence (
  evidence_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  path TEXT NOT NULL,
  blob_sha TEXT NOT NULL REFERENCES blobs(sha256),
  locator_json TEXT NOT NULL,
  excerpt TEXT NOT NULL,
  retrieved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS services (
  service_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  aliases_json TEXT NOT NULL DEFAULT '[]',
  root_path TEXT NOT NULL DEFAULT '',
  summary TEXT
);

CREATE TABLE IF NOT EXISTS claims (
  claim_id TEXT PRIMARY KEY,
  service_id TEXT,
  facet TEXT NOT NULL,
  kind TEXT NOT NULL,
  statement TEXT NOT NULL,
  predicate TEXT NOT NULL,
  object_value TEXT,
  evidence_ids_json TEXT NOT NULL DEFAULT '[]',
  confidence REAL,
  gap_reason TEXT,
  producer TEXT NOT NULL,
  FOREIGN KEY(service_id) REFERENCES services(service_id)
);

CREATE TABLE IF NOT EXISTS relations (
  relation_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  from_service_id TEXT NOT NULL REFERENCES services(service_id),
  to_ref TEXT NOT NULL,
  epistemic TEXT NOT NULL,
  evidence_ids_json TEXT NOT NULL DEFAULT '[]',
  facet TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_id(*parts: str) -> str:
    h = hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()
    return h[:24]


class ExpedienteStore:
    def __init__(self, workspace: Path, db_filename: str = "expediente.sqlite3", blobs_dirname: str = "blobs"):
        self.workspace = workspace
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.blobs_dir = self.workspace / blobs_dirname
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.workspace / db_filename
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def put_blob(self, data: bytes) -> str:
        sha = hashlib.sha256(data).hexdigest()
        dest = self.blobs_dir / sha
        if not dest.exists():
            dest.write_bytes(data)
            self._conn.execute(
                "INSERT OR IGNORE INTO blobs(sha256, size_bytes, stored_at) VALUES (?, ?, ?)",
                (sha, len(data), utc_now()),
            )
            self._conn.commit()
        return sha

    def get_blob(self, sha: str) -> bytes:
        return (self.blobs_dir / sha).read_bytes()

    def start_run(self, source_uri: str) -> str:
        run_id = stable_id("run", source_uri, utc_now())
        self._conn.execute(
            "INSERT INTO runs(run_id, source_uri, started_at) VALUES (?, ?, ?)",
            (run_id, source_uri, utc_now()),
        )
        self._conn.commit()
        return run_id

    def finish_run(self, receipt: RunReceipt) -> None:
        self._conn.execute(
            """
            UPDATE runs SET finished_at=?, files_seen=?, files_ingested=?, files_skipped=?,
              claims_written=?, gaps_written=?, errors_json=?
            WHERE run_id=?
            """,
            (
                receipt.finished_at or utc_now(),
                receipt.files_seen,
                receipt.files_ingested,
                receipt.files_skipped,
                receipt.claims_written,
                receipt.gaps_written,
                json.dumps(receipt.errors),
                receipt.run_id,
            ),
        )
        self._conn.commit()

    def add_document(self, source_id: str, path: str, blob_sha: str, run_id: str) -> str:
        doc_id = stable_id("doc", source_id, path, blob_sha)
        self._conn.execute(
            """
            INSERT OR IGNORE INTO documents(doc_id, source_id, path, blob_sha, run_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (doc_id, source_id, path, blob_sha, run_id),
        )
        self._conn.commit()
        return doc_id

    def add_evidence(self, ev: Evidence) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO evidence(
              evidence_id, source_id, path, blob_sha, locator_json, excerpt, retrieved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ev.evidence_id,
                ev.source_id,
                ev.path,
                ev.blob_sha,
                json.dumps(ev.locator.to_json()),
                ev.excerpt,
                ev.retrieved_at,
            ),
        )
        self._conn.commit()

    def upsert_service(self, svc: Service) -> None:
        self._conn.execute(
            """
            INSERT INTO services(service_id, name, aliases_json, root_path, summary)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(service_id) DO UPDATE SET
              name=excluded.name,
              aliases_json=excluded.aliases_json,
              root_path=excluded.root_path,
              summary=excluded.summary
            """,
            (svc.service_id, svc.name, json.dumps(svc.aliases), svc.root_path, svc.summary),
        )
        self._conn.commit()

    def add_claim(self, claim: Claim) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO claims(
              claim_id, service_id, facet, kind, statement, predicate, object_value,
              evidence_ids_json, confidence, gap_reason, producer
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim.claim_id,
                claim.service_id,
                claim.facet.value,
                claim.kind.value,
                claim.statement,
                claim.predicate,
                claim.object_value,
                json.dumps(claim.evidence_ids),
                claim.confidence,
                claim.gap_reason,
                claim.producer,
            ),
        )
        self._conn.commit()

    def add_relation(self, rel: Relation) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO relations(
              relation_id, kind, from_service_id, to_ref, epistemic, evidence_ids_json, facet
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rel.relation_id,
                rel.kind,
                rel.from_service_id,
                rel.to_ref,
                rel.epistemic.value,
                json.dumps(rel.evidence_ids),
                rel.facet.value,
            ),
        )
        self._conn.commit()

    def list_services(self) -> list[Service]:
        rows = self._conn.execute("SELECT * FROM services ORDER BY name").fetchall()
        return [
            Service(
                service_id=r["service_id"],
                name=r["name"],
                aliases=json.loads(r["aliases_json"]),
                root_path=r["root_path"],
                summary=r["summary"],
            )
            for r in rows
        ]

    def get_service(self, name_or_id: str) -> Service | None:
        key = name_or_id.strip().lower()
        for svc in self.list_services():
            if svc.service_id == name_or_id or svc.name.lower() == key:
                return svc
            if key in [a.lower() for a in svc.aliases]:
                return svc
        return None

    def claims_for(self, service_id: str) -> list[Claim]:
        rows = self._conn.execute(
            "SELECT * FROM claims WHERE service_id=? ORDER BY facet, kind, statement",
            (service_id,),
        ).fetchall()
        return [self._row_to_claim(r) for r in rows]

    def relations_for(self, service_id: str) -> list[Relation]:
        rows = self._conn.execute(
            "SELECT * FROM relations WHERE from_service_id=? ORDER BY kind, to_ref",
            (service_id,),
        ).fetchall()
        out: list[Relation] = []
        for r in rows:
            out.append(
                Relation(
                    relation_id=r["relation_id"],
                    kind=r["kind"],
                    from_service_id=r["from_service_id"],
                    to_ref=r["to_ref"],
                    epistemic=EpistemicKind(r["epistemic"]),
                    evidence_ids=json.loads(r["evidence_ids_json"]),
                    facet=Facet(r["facet"]),
                )
            )
        return out

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        r = self._conn.execute(
            "SELECT * FROM evidence WHERE evidence_id=?", (evidence_id,)
        ).fetchone()
        if not r:
            return None
        return Evidence(
            evidence_id=r["evidence_id"],
            source_id=r["source_id"],
            path=r["path"],
            blob_sha=r["blob_sha"],
            locator=Locator.from_json(json.loads(r["locator_json"])),
            excerpt=r["excerpt"],
            retrieved_at=r["retrieved_at"],
        )

    def latest_run(self) -> dict[str, Any] | None:
        r = self._conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return dict(r) if r else None

    def coverage_for(self, service_id: str) -> dict[str, Any]:
        claims = self.claims_for(service_id)
        by_facet: dict[str, dict[str, int]] = {}
        for facet in Facet:
            by_facet[facet.value] = {"observed": 0, "inferred": 0, "gap": 0}
        for c in claims:
            by_facet[c.facet.value][c.kind.value] += 1
        return by_facet

    @staticmethod
    def _row_to_claim(r: sqlite3.Row) -> Claim:
        return Claim(
            claim_id=r["claim_id"],
            service_id=r["service_id"],
            facet=Facet(r["facet"]),
            kind=EpistemicKind(r["kind"]),
            statement=r["statement"],
            predicate=r["predicate"],
            object_value=r["object_value"],
            evidence_ids=json.loads(r["evidence_ids_json"]),
            confidence=r["confidence"],
            gap_reason=r["gap_reason"],
            producer=r["producer"],
        )

    def open_excerpt(self, evidence_id: str) -> str | None:
        ev = self.get_evidence(evidence_id)
        if not ev:
            return None
        raw = self.get_blob(ev.blob_sha)
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        loc = ev.locator
        if loc.kind == "line_range" and loc.start_line:
            start = max(loc.start_line - 1, 0)
            end = loc.end_line or loc.start_line
            return "\n".join(lines[start:end])
        return ev.excerpt
