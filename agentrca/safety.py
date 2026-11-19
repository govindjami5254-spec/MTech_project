"""Safety layer: redaction, untrusted-input handling, tool policy and audit log.

Design rule: the LLM can only *request* tools. This module (plain code, no LLM)
decides whether a request is allowed, validates every argument, and records
every decision in an append-only JSONL audit log.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .models import ToolDef, norm_severity, SEVERITY_RANK

# ---------------------------------------------------------------- redaction
_REDACTIONS = [
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\s*[=:]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer [REDACTED]"),
    (re.compile(r"\b(?:sk|pk|ghp|AKIA)[A-Za-z0-9_\-]{12,}\b"), "[REDACTED_KEY]"),
    (re.compile(r"\b[\w.+\-]+@[\w\-]+\.[\w.\-]+\b"), "[REDACTED_EMAIL]"),
]

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_INJECTION = re.compile(
    r"(?i)(ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+instructions"
    r"|disregard\s+(the\s+)?(previous|above|system)"
    r"|you\s+are\s+now\b|system\s+prompt|new\s+instructions?\s*:"
    r"|\bcall\s+(the\s+)?tool\b|\brun_shell\b|\brm\s+-rf\b|\bexec(ute)?\s*\()"
)


def redact(text: str) -> str:
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


def sanitize(text: str, max_chars: int) -> str:
    """Strip control characters and neutralise our own data delimiters."""
    text = _CONTROL.sub(" ", text)
    text = text.replace("<log_data>", "[log_data]").replace("</log_data>", "[/log_data]")
    return text[:max_chars]


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION.search(text))


def wrap_untrusted(lines: list[str]) -> str:
    return "<log_data>\n" + "\n".join(lines) + "\n</log_data>"


# ---------------------------------------------------------------- path safety
class PathViolation(Exception):
    pass


def resolve_inside(root: str | Path, candidate: str | Path) -> Path:
    """Resolve `candidate` and refuse anything that escapes `root` (.., symlinks)."""
    root_p = Path(root).resolve()
    cand = Path(candidate)
    full = (cand if cand.is_absolute() else root_p / cand).resolve()
    if not full.is_relative_to(root_p):
        raise PathViolation(f"path escapes allowed root: {candidate}")
    return full


# ---------------------------------------------------------------- audit log
class AuditLog:
    """Append-only JSONL audit trail (also kept in memory for metrics)."""

    def __init__(self, path: Optional[Path], run_id: str):
        self.path = Path(path) if path else None
        self.run_id = run_id
        self.entries: list[dict] = []
        self._lock = threading.Lock()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, kind: str, **fields: Any) -> None:
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "run_id": self.run_id,
                 "kind": kind, **fields}
        with self._lock:
            self.entries.append(entry)
            if self.path:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, default=str) + "\n")

    def count(self, kind: str) -> int:
        return sum(1 for e in self.entries if e["kind"] == kind)


# ---------------------------------------------------------------- tool policy
class PolicyViolation(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ToolPolicy:
    """Allowlist + strict argument validation for every tool call."""

    def __init__(self, tool_defs: dict[str, ToolDef], allowed: list[str]):
        self.defs = tool_defs
        self.allowed = set(allowed)

    def validate(self, name: str, args: Any) -> dict:
        if not isinstance(name, str) or name not in self.allowed or name not in self.defs:
            raise PolicyViolation("tool_not_allowed", f"tool '{name}' is not on the allowlist")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise PolicyViolation("invalid_arguments", "arguments must be an object")
        d = self.defs[name]
        known = {p.name: p for p in d.params}
        for key in args:
            if key not in known:
                raise PolicyViolation("invalid_arguments", f"unknown argument '{key}'")
        clean: dict = {}
        for p in d.params:
            val = args.get(p.name)
            if val is None or val == "":
                if p.required:
                    raise PolicyViolation("invalid_arguments", f"missing required argument '{p.name}'")
                continue
            clean[p.name] = self._check(p, val)
        return clean

    @staticmethod
    def _check(p, val):
        if p.type == "integer":
            try:
                if isinstance(val, bool):
                    raise ValueError
                val = int(val)
            except (TypeError, ValueError):
                raise PolicyViolation("invalid_arguments", f"'{p.name}' must be an integer")
            if p.minimum is not None and val < p.minimum or p.maximum is not None and val > p.maximum:
                raise PolicyViolation("invalid_arguments",
                                      f"'{p.name}' out of range [{p.minimum}, {p.maximum}]")
            return val
        if not isinstance(val, str):
            raise PolicyViolation("invalid_arguments", f"'{p.name}' must be a string")
        val = val.strip()
        if len(val) > p.maxlen:
            raise PolicyViolation("invalid_arguments", f"'{p.name}' longer than {p.maxlen} chars")
        if _CONTROL.search(val):
            raise PolicyViolation("invalid_arguments", f"'{p.name}' contains control characters")
        if p.enum is not None:
            val = norm_severity(val) if set(p.enum) <= set(SEVERITY_RANK) else val
            if val not in p.enum:
                raise PolicyViolation("invalid_arguments", f"'{p.name}' must be one of {list(p.enum)}")
        if p.is_time:
            from .ingest import parse_ts
            try:
                parse_ts(val)
            except ValueError:
                raise PolicyViolation("invalid_arguments", f"'{p.name}' must be an ISO-8601 timestamp")
        return val
