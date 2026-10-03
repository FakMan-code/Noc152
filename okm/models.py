"""Shared types for the operational expediente.

Epistemic kinds:
  observed  — backed by addressable evidence
  inferred  — derived without hard proof (or weak heuristic)
  gap       — something we looked for and did not find
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EpistemicKind(str, Enum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    GAP = "gap"


class Facet(str, Enum):
    IDENTITY = "identity"
    TOPOLOGY = "topology"
    RUNTIME = "runtime"
    SIGNALS = "signals"
    FAILURE = "failure"


@dataclass(frozen=True)
class Locator:
    """Where inside a blob the evidence lives."""

    kind: str  # line_range | whole_file | key_path
    start_line: int | None = None
    end_line: int | None = None
    key: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "key": self.key,
        }

    @staticmethod
    def from_json(data: dict[str, Any]) -> "Locator":
        return Locator(
            kind=data["kind"],
            start_line=data.get("start_line"),
            end_line=data.get("end_line"),
            key=data.get("key"),
        )

    def __str__(self) -> str:
        if self.kind == "line_range" and self.start_line is not None:
            end = self.end_line or self.start_line
            if end == self.start_line:
                return f"L{self.start_line}"
            return f"L{self.start_line}-{end}"
        if self.kind == "key_path" and self.key:
            return self.key
        return self.kind


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source_id: str
    path: str
    blob_sha: str
    locator: Locator
    excerpt: str
    retrieved_at: str

    def openable_ref(self) -> str:
        return f"{self.path}:{self.locator}"


@dataclass
class Claim:
    claim_id: str
    service_id: str | None
    facet: Facet
    kind: EpistemicKind
    statement: str
    predicate: str
    object_value: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float | None = None
    gap_reason: str | None = None
    producer: str = "extractor"


@dataclass
class Service:
    service_id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    root_path: str = ""
    summary: str | None = None


@dataclass
class Relation:
    relation_id: str
    kind: str
    from_service_id: str
    to_ref: str
    epistemic: EpistemicKind
    evidence_ids: list[str] = field(default_factory=list)
    facet: Facet = Facet.TOPOLOGY


@dataclass
class RunReceipt:
    run_id: str
    source_uri: str
    started_at: str
    finished_at: str | None = None
    files_seen: int = 0
    files_ingested: int = 0
    files_skipped: int = 0
    claims_written: int = 0
    gaps_written: int = 0
    errors: list[str] = field(default_factory=list)
