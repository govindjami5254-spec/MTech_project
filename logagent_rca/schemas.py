"""Shared data contracts for LogAgent-RCA (M1).

Design rules encoded here:
* Agent-visible data (``CaseManifest``, ``LogEvent``, ``Evidence``) and ground truth
  (``GroundTruth``) are separate models. ``CaseManifest`` forbids extra fields, so truth
  fields cannot be smuggled into a case bundle.
* ``FinalReport`` is the single output schema shared by E2b and E3 (and scored for A2/A3).
  Its length limits bound model output tokens on CPU.
* ``RunMetrics`` enforces the strict unique-evidence-token budget B and records total
  processed tokens separately; equal total compute is *not* implied.
"""
from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Optional

from pydantic import (AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints,
                      field_validator, model_validator)

SCHEMA_VERSION = "1"

# ------------------------------------------------------------------ primitives
ComponentName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
EvidenceId = Annotated[str, StringConstraints(pattern=r"^E[1-9][0-9]{0,5}$")]
CaseId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_relative_path(value: str) -> str:
    """Accept only relative POSIX paths without traversal (agent-visible file references)."""
    if not value or value.startswith("/") or "\\" in value or ":" in value:
        raise ValueError(f"path must be relative POSIX without ':' or '\\': {value!r}")
    parts = value.split("/")
    for part in parts:
        if part in ("", ".", "..") or not _SAFE_SEGMENT.match(part):
            raise ValueError(f"unsafe path segment in {value!r}")
    return value


RelPath = Annotated[str, StringConstraints(min_length=1, max_length=200)]
EventUid = Annotated[str, StringConstraints(min_length=3, max_length=220)]


def validate_uid(value: str) -> str:
    """Event uid is '<relative source path>:<line number>'."""
    src, sep, line = value.rpartition(":")
    if not sep or not line.isdigit() or int(line) < 1:
        raise ValueError(f"uid must be '<source>:<line>': {value!r}")
    validate_relative_path(src)
    return value


class Severity(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    FATAL = "FATAL"

    @property
    def rank(self) -> int:
        return _RANK[self]


_RANK = {Severity.DEBUG: 10, Severity.INFO: 20, Severity.WARN: 30, Severity.ERROR: 40, Severity.FATAL: 50}
_SEVERITY_ALIASES = {"WARNING": "WARN", "ERR": "ERROR", "CRITICAL": "FATAL", "CRIT": "FATAL",
                     "TRACE": "DEBUG", "SEVERE": "ERROR", "FINE": "DEBUG", "NOTICE": "INFO"}


def normalize_severity(value: Any) -> Severity:
    if isinstance(value, Severity):
        return value
    text = str(value or "").strip().upper()
    text = _SEVERITY_ALIASES.get(text, text)
    try:
        return Severity(text)
    except ValueError as exc:
        raise ValueError(f"unknown severity {value!r}") from exc


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


class Split(str, Enum):
    DEV = "dev"
    TEST = "test"


class Stratum(str, Enum):
    EASY = "easy"
    MULTI_HOP = "multi_hop"
    DISTRACTOR = "distractor"
    OVER_BUDGET = "over_budget"
    CONCURRENT = "concurrent"
    INSUFFICIENT = "insufficient"


class ArmId(str, Enum):
    E1 = "E1"      # rule-based RCA (dependency-following rules authored on dev data)
    E1F = "E1f"    # log-free floor: names the incident's own component (no log evidence)
    E2B = "E2b"    # strong single-pass LLM
    E3 = "E3"      # iterative agentic RCA
    A2 = "A2"      # E3 without coverage gate
    A3 = "A3"      # E3 without grounding validator (scored from E3 raw output, no extra runs)


class RunStatus(str, Enum):
    OK = "ok"
    FAILED = "failed"        # LLM / parse failure after retries -> scored as incorrect
    ABORTED = "aborted"      # safety or time budget stop


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ------------------------------------------------------------- agent-visible data
class LogEvent(_Frozen):
    uid: EventUid
    ts: AwareDatetime
    severity: Severity
    component: ComponentName
    message: Annotated[str, StringConstraints(max_length=2000)]
    source: RelPath
    line_no: Annotated[int, Field(ge=1)]
    suspicious: bool = False          # looks like prompt injection (flag only, never trusted)

    @field_validator("uid")
    @classmethod
    def _check_uid(cls, v):
        return validate_uid(v)

    @field_validator("source")
    @classmethod
    def _check_source(cls, v):
        return validate_relative_path(v)

    @field_validator("severity", mode="before")
    @classmethod
    def _sev(cls, v):
        return normalize_severity(v)

    @field_validator("ts")
    @classmethod
    def _utc(cls, v):
        return _to_utc(v)

    @model_validator(mode="after")
    def _uid_matches(self):
        if self.uid != f"{self.source}:{self.line_no}":
            raise ValueError("uid must equal '<source>:<line_no>'")
        return self


class Evidence(_Frozen):
    """A log event that was presented to a model, with provenance and token cost."""
    id: EvidenceId
    uid: EventUid
    ts: AwareDatetime
    severity: Severity
    component: ComponentName
    source: RelPath
    line_no: Annotated[int, Field(ge=1)]
    message: Annotated[str, StringConstraints(max_length=2000)]
    step: Annotated[int, Field(ge=0)]             # 0 = incident trigger / single-pass packing
    tool: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    tokens: Annotated[int, Field(ge=1)]           # counted once, when first presented
    suspicious: bool = False

    @field_validator("uid")
    @classmethod
    def _check_uid(cls, v):
        return validate_uid(v)

    @field_validator("source")
    @classmethod
    def _check_source(cls, v):
        return validate_relative_path(v)

    @field_validator("severity", mode="before")
    @classmethod
    def _sev(cls, v):
        return normalize_severity(v)

    @field_validator("ts")
    @classmethod
    def _utc(cls, v):
        return _to_utc(v)


class Incident(_Frozen):
    id: Annotated[str, StringConstraints(pattern=r"^INC-[0-9]{3,6}$")]
    rule_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,47}$")]
    description: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    ts: AwareDatetime
    trigger_uid: EventUid
    trigger_component: ComponentName

    @field_validator("trigger_uid")
    @classmethod
    def _check_uid(cls, v):
        return validate_uid(v)

    @field_validator("ts")
    @classmethod
    def _utc(cls, v):
        return _to_utc(v)


class CaseManifest(_Frozen):
    """``incident.json`` inside a case bundle. Everything here is visible to every arm.

    ``extra='forbid'`` means ground-truth fields (root cause, family, stratum, ...) are
    rejected if a generator bug tries to write them into the bundle.
    """
    schema_version: str = SCHEMA_VERSION
    case_id: CaseId
    split: Split
    incident: Incident
    log_files: Annotated[list[RelPath], Field(min_length=1, max_length=50)]

    @field_validator("log_files")
    @classmethod
    def _files(cls, v):
        for p in v:
            validate_relative_path(p)
        if len(set(v)) != len(v):
            raise ValueError("duplicate log file")
        return v


# ------------------------------------------------------------------ ground truth
class GroundTruth(_Frozen):
    """Stored outside case bundles; loaded only by the scorer."""
    schema_version: str = SCHEMA_VERSION
    case_id: CaseId
    split: Split
    family_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
    stratum: Stratum
    root_causes: Annotated[list[ComponentName], Field(max_length=3)]
    fault_type: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    expected_abstain: bool = False
    key_evidence: list[EventUid] = Field(default_factory=list)
    relevant_evidence: list[EventUid] = Field(default_factory=list)
    propagation_path: list[ComponentName] = Field(default_factory=list)   # cause -> ... -> symptom
    injection_uids: list[EventUid] = Field(default_factory=list)
    decoy_component: Optional[ComponentName] = None

    @field_validator("key_evidence", "relevant_evidence", "injection_uids")
    @classmethod
    def _uids(cls, v):
        for u in v:
            validate_uid(u)
        return v

    @model_validator(mode="after")
    def _consistency(self):
        if self.stratum == Stratum.INSUFFICIENT and not self.expected_abstain:
            raise ValueError("insufficient-evidence cases must expect abstention")
        if not self.expected_abstain:
            if not self.root_causes:
                raise ValueError("root_causes required unless abstention is expected")
            if not self.key_evidence:
                raise ValueError("key_evidence required unless abstention is expected")
        if not set(self.key_evidence) <= set(self.relevant_evidence):
            raise ValueError("key_evidence must be a subset of relevant_evidence")
        if self.stratum == Stratum.CONCURRENT and len(self.root_causes) < 2:
            raise ValueError("concurrent cases need at least two root causes")
        if self.propagation_path and self.root_causes and self.propagation_path[0] not in self.root_causes:
            raise ValueError("propagation_path must start at a root cause")
        return self


# ------------------------------------------------------------- shared output
# Output limits are deliberately tight: CPU generation is the dominant cost (M5 measurement:
# ~1.3-1.6 output tokens/s under shared-server load).
_TEXT = Annotated[str, StringConstraints(min_length=1, max_length=160)]


class Claim(_Frozen):
    text: _TEXT
    evidence_ids: Annotated[list[EvidenceId], Field(max_length=4)]


class Hypothesis(_Frozen):
    cause_component: ComponentName
    cause_summary: _TEXT
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    claims: Annotated[list[Claim], Field(min_length=1, max_length=3)]


class FinalReport(_Frozen):
    """The single final-answer schema used by E2b and E3 (identical prompt contract)."""
    insufficient_evidence: bool
    hypotheses: Annotated[list[Hypothesis], Field(max_length=3)]
    evidence_gaps: Annotated[list[_TEXT], Field(max_length=2)]
    recommendations: Annotated[list[_TEXT], Field(max_length=2)]

    @property
    def abstained(self) -> bool:
        return self.insufficient_evidence or not self.hypotheses


def _inline_refs(schema: dict) -> dict:
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].rsplit("/", 1)[-1]
                return resolve(copy.deepcopy(defs[name]))
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(x) for x in node]
        return node

    return resolve(schema)


def final_report_json_schema() -> dict:
    """JSON schema for Ollama's ``format`` field, with all ``$ref``s inlined."""
    return _inline_refs(FinalReport.model_json_schema())


# ---------------------------------------------------------- run provenance
class ModelInfo(_Frozen):
    name: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    manifest_digest: Sha256Hex                    # as reported by Ollama /api/tags
    weights_digest: Optional[Sha256Hex] = None    # GGUF blob digest (stable across installs)
    quantization: Optional[str] = None
    parameter_size: Optional[str] = None
    ollama_version: Optional[str] = None
    num_ctx: Annotated[int, Field(ge=512)]
    temperature: Annotated[float, Field(ge=0.0, le=2.0)]
    seed: int
    think: bool
    num_predict: Annotated[int, Field(ge=1)]


class ToolCallRecord(_Frozen):
    step: Annotated[int, Field(ge=1)]
    tool: Annotated[str, StringConstraints(max_length=80)]
    args: dict[str, Any] = Field(default_factory=dict)
    allowed: bool
    error_code: Optional[str] = None
    evidence_ids: list[EvidenceId] = Field(default_factory=list)
    new_evidence_tokens: Annotated[int, Field(ge=0)] = 0
    output_chars: Annotated[int, Field(ge=0)] = 0
    ms: Annotated[float, Field(ge=0.0)] = 0.0


class RunMetrics(_Frozen):
    evidence_token_budget: Annotated[int, Field(ge=1)]           # B
    unique_evidence_tokens: Annotated[int, Field(ge=0)]          # must be <= B (strict)
    unique_evidence_items: Annotated[int, Field(ge=0)] = 0
    llm_calls: Annotated[int, Field(ge=0)] = 0
    prompt_tokens_total: Annotated[int, Field(ge=0)] = 0         # all processed prompt tokens
    output_tokens_total: Annotated[int, Field(ge=0)] = 0
    llm_seconds: Annotated[float, Field(ge=0.0)] = 0.0
    wall_seconds: Annotated[float, Field(ge=0.0)] = 0.0
    steps: Annotated[int, Field(ge=0)] = 0
    tool_calls: Annotated[int, Field(ge=0)] = 0
    blocked_tool_calls: Annotated[int, Field(ge=0)] = 0
    gate_rounds: Annotated[int, Field(ge=0)] = 0
    parse_failures: Annotated[int, Field(ge=0)] = 0
    cpu_seconds: Optional[Annotated[float, Field(ge=0.0)]] = None    # Ollama process CPU time
    peak_rss_mb: Optional[Annotated[float, Field(ge=0.0)]] = None
    mean_cpu_percent: Optional[Annotated[float, Field(ge=0.0)]] = None

    @model_validator(mode="after")
    def _strict_budget(self):
        if self.unique_evidence_tokens > self.evidence_token_budget:
            raise ValueError(f"evidence budget exceeded: {self.unique_evidence_tokens} > "
                             f"{self.evidence_token_budget}")
        return self


class ValidationStats(_Frozen):
    """Grounding-validator outcome computed on the RAW report (what the model actually claimed)."""
    claims_total: Annotated[int, Field(ge=0)]
    claims_supported: Annotated[int, Field(ge=0)]
    fabricated_ids: Annotated[int, Field(ge=0)]
    suspicious_citations: Annotated[int, Field(ge=0)]
    hypotheses_in: Annotated[int, Field(ge=0)]
    hypotheses_dropped: Annotated[int, Field(ge=0)]
    abstained_by_validator: bool

    @property
    def unsupported_claim_rate(self) -> float:
        return 0.0 if not self.claims_total else (self.claims_total - self.claims_supported) / self.claims_total

    @model_validator(mode="after")
    def _counts(self):
        if self.claims_supported > self.claims_total or self.hypotheses_dropped > self.hypotheses_in:
            raise ValueError("inconsistent validation counts")
        return self


class RunRecord(_Frozen):
    schema_version: str = SCHEMA_VERSION
    run_id: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    case_id: CaseId
    split: Split
    arm: ArmId
    repeat: Annotated[int, Field(ge=0)]
    config_hash: Sha256Hex
    code_commit: Optional[Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{7,40}$")]] = None
    model: Optional[ModelInfo] = None             # None for E1 (no LLM)
    started_at: AwareDatetime
    status: RunStatus
    error: Optional[Annotated[str, StringConstraints(max_length=500)]] = None
    report_raw: Optional[FinalReport] = None       # model output before validation (A3 scoring)
    report_validated: Optional[FinalReport] = None # after grounding validator (E3/E2b scoring)
    validation: Optional[ValidationStats] = None   # validator stats on report_raw
    evidence: list[Evidence] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    metrics: RunMetrics

    @model_validator(mode="after")
    def _consistency(self):
        if self.arm == ArmId.A3:
            raise ValueError("A3 is derived from E3 report_raw; it is never a separate run")
        if self.arm not in (ArmId.E1, ArmId.E1F) and self.model is None:
            raise ValueError("LLM arms must record model provenance")
        if self.status == RunStatus.OK and self.report_raw is None:
            raise ValueError("successful runs must store report_raw")
        if self.arm in (ArmId.E1, ArmId.E1F, ArmId.E2B) and self.tool_calls:
            raise ValueError("non-agentic arms cannot have tool calls")
        tokens = sum(e.tokens for e in self.evidence)
        if tokens != self.metrics.unique_evidence_tokens:
            raise ValueError("metrics.unique_evidence_tokens must equal the sum over evidence")
        if len({e.uid for e in self.evidence}) != len(self.evidence):
            raise ValueError("evidence must be unique per run")
        return self
