"""Per-case context and per-arm result containers shared by all arms."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Optional

from .config import Config
from .evidence import EvidenceLedger
from .index import LogIndex
from .ingest import IngestStats, load_case
from .schemas import CaseManifest, FinalReport, LogEvent, RunStatus, ToolCallRecord


@dataclass
class CaseContext:
    case_dir: Path
    manifest: CaseManifest
    index: LogIndex
    stats: IngestStats

    @property
    def trigger(self) -> LogEvent:
        return self.index.get(self.manifest.incident.trigger_uid)

    def window(self, lookback_s: int, after_s: int = 120):
        ts = self.manifest.incident.ts
        return ts - timedelta(seconds=lookback_s), ts + timedelta(seconds=after_s)


def open_case(case_dir: str | Path, cfg: Config) -> CaseContext:
    manifest, events, stats = load_case(case_dir, cfg.ingest, cfg.safety.redact)
    return CaseContext(Path(case_dir), manifest, LogIndex(events), stats)


@dataclass
class LLMUsage:
    calls: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    parse_failures: int = 0
    normalised_fields: int = 0        # over-long fields truncated to schema limits


@dataclass
class ArmResult:
    report_raw: Optional[FinalReport]
    ledger: EvidenceLedger
    status: RunStatus = RunStatus.OK
    error: Optional[str] = None
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    llm: LLMUsage = field(default_factory=LLMUsage)
    steps: int = 0
    gate_rounds: int = 0
    blocked_calls: int = 0
    notes: dict = field(default_factory=dict)
