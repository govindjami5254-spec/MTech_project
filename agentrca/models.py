"""Core data types shared by all AgentRCA modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

SEVERITY_RANK = {
    "DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40, "FATAL": 50,
}
_ALIASES = {"WARNING": "WARN", "CRITICAL": "FATAL", "ERR": "ERROR", "TRACE": "DEBUG"}


def norm_severity(value: str) -> str:
    v = (value or "").strip().upper()
    return _ALIASES.get(v, v) if v else "INFO"


def sev_rank(value: str) -> int:
    return SEVERITY_RANK.get(norm_severity(value), 20)


@dataclass(frozen=True)
class LogEvent:
    uid: str            # "<relative posix path>:<line number>" - stable evidence key
    ts: datetime        # timezone-aware UTC
    severity: str
    component: str
    message: str        # already redacted + sanitized + truncated
    source: str
    line_no: int
    suspicious: bool = False   # looks like a prompt-injection attempt


@dataclass
class Incident:
    id: str
    rule_id: str
    description: str
    priority: int
    trigger: LogEvent
    ts: datetime
    diagnosis_hint: Optional[str] = None


@dataclass(frozen=True)
class Param:
    name: str
    type: str                      # "string" | "integer"
    description: str = ""
    required: bool = False
    maxlen: int = 64
    enum: Optional[tuple] = None
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    is_time: bool = False


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    params: tuple = field(default_factory=tuple)


@dataclass
class ToolResult:
    ok: bool
    text: str
    evidence_ids: list = field(default_factory=list)
    error_code: Optional[str] = None
    data: Any = None
