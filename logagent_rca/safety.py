"""Safety layer (M6): tool allowlist, strict argument validation and an append-only audit log.

The LLM can only *request* tools. This plain-code layer decides, validates every argument against a
declared schema (types, ranges, lengths, enums, timestamps; unknown arguments rejected) and records
every decision, including blocked requests and suspected prompt-injection lines shown to the model.
No tool takes a file path, command, URL or regular expression.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .ingest import parse_ts
from .schemas import Severity

_CTRL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class Param:
    name: str
    type: str                    # "string" | "integer"
    description: str
    required: bool = False
    maxlen: int = 64
    enum: Optional[tuple] = None
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    is_time: bool = False


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    params: tuple

    def ollama(self) -> dict:
        props = {}
        for p in self.params:
            prop = {"type": p.type, "description": p.description}
            if p.enum:
                prop["enum"] = list(p.enum)
            props[p.name] = prop
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": {"type": "object", "properties": props,
                           "required": [p.name for p in self.params if p.required]}}}


class PolicyViolation(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class ToolPolicy:
    def __init__(self, specs: dict[str, ToolSpec], allowed: list[str]):
        self.specs, self.allowed = specs, set(allowed)

    def validate(self, name: Any, args: Any) -> dict:
        if not isinstance(name, str) or name not in self.allowed or name not in self.specs:
            raise PolicyViolation("tool_not_allowed", f"tool {str(name)[:40]!r} is not on the allowlist")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise PolicyViolation("invalid_arguments", "arguments must be an object")
        known = {p.name: p for p in self.specs[name].params}
        for key in args:
            if key not in known:
                raise PolicyViolation("invalid_arguments", f"unknown argument {str(key)[:40]!r}")
        clean = {}
        for p in known.values():
            val = args.get(p.name)
            if val is None or val == "":
                if p.required:
                    raise PolicyViolation("invalid_arguments", f"missing required argument {p.name!r}")
                continue
            clean[p.name] = self._check(p, val)
        return clean

    @staticmethod
    def _check(p: Param, val):
        if p.type == "integer":
            if isinstance(val, bool):
                raise PolicyViolation("invalid_arguments", f"{p.name!r} must be an integer")
            try:
                val = int(val)
            except (TypeError, ValueError):
                raise PolicyViolation("invalid_arguments", f"{p.name!r} must be an integer")
            if (p.minimum is not None and val < p.minimum) or (p.maximum is not None and val > p.maximum):
                raise PolicyViolation("invalid_arguments", f"{p.name!r} must be in [{p.minimum}, {p.maximum}]")
            return val
        if not isinstance(val, str):
            raise PolicyViolation("invalid_arguments", f"{p.name!r} must be a string")
        val = val.strip()
        if len(val) > p.maxlen:
            raise PolicyViolation("invalid_arguments", f"{p.name!r} longer than {p.maxlen} characters")
        if _CTRL.search(val):
            raise PolicyViolation("invalid_arguments", f"{p.name!r} contains control characters")
        if p.enum is not None:
            v = val.upper().replace("WARNING", "WARN")
            if v not in p.enum:
                raise PolicyViolation("invalid_arguments", f"{p.name!r} must be one of {list(p.enum)}")
            val = v
        if p.is_time:
            try:
                parse_ts(val)
            except ValueError:
                raise PolicyViolation("invalid_arguments", f"{p.name!r} must be an ISO-8601 timestamp")
        return val


class AuditLog:
    """Append-only JSONL audit trail; also kept in memory for metrics."""

    def __init__(self, path: Optional[str | Path], run_id: str):
        self.path = Path(path) if path else None
        self.run_id = run_id
        self.entries: list[dict] = []
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, kind: str, **fields: Any) -> None:
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "run_id": self.run_id, "kind": kind, **fields}
        self.entries.append(entry)
        if self.path:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")

    def count(self, kind: str) -> int:
        return sum(1 for e in self.entries if e["kind"] == kind)


SEVERITIES = tuple(s.value for s in Severity)
