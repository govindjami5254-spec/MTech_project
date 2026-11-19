"""Log ingestion: bounded, path-safe, configurable parsing into a LogIndex."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import LogsConfig
from .models import LogEvent, norm_severity, sev_rank
from .safety import PathViolation, looks_like_injection, redact, sanitize


class IngestError(Exception):
    pass


def parse_ts(value: str) -> datetime:
    s = value.strip().replace(",", ".")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class LogIndex:
    """Time-ordered, read-only view over all ingested events."""

    def __init__(self, events: list[LogEvent], stats: Optional[dict] = None):
        self.events = sorted(events, key=lambda e: (e.ts, e.source, e.line_no))
        self._pos = {e.uid: i for i, e in enumerate(self.events)}
        self.by_component: dict[str, list[LogEvent]] = defaultdict(list)
        for e in self.events:
            self.by_component[e.component].append(e)
        self.stats = stats or {}

    @property
    def components(self) -> list[str]:
        return sorted(self.by_component)

    def get(self, uid: str) -> Optional[LogEvent]:
        i = self._pos.get(uid)
        return self.events[i] if i is not None else None

    def search(self, component=None, contains=None, min_severity="DEBUG",
               start=None, end=None, limit=25) -> tuple[list[LogEvent], int]:
        pool = self.by_component.get(component, []) if component else self.events
        needle = contains.lower() if contains else None
        floor = sev_rank(min_severity)
        out = []
        for e in pool:
            if sev_rank(e.severity) < floor:
                continue
            if start and e.ts < start or end and e.ts > end:
                continue
            if needle and needle not in e.message.lower():
                continue
            out.append(e)
        return out[:limit], len(out)

    def context(self, uid: str, before: int, after: int) -> list[LogEvent]:
        i = self._pos.get(uid)
        if i is None:
            return []
        return self.events[max(0, i - before): i + after + 1]

    def count(self, contains: str, component=None) -> dict[str, int]:
        needle = contains.lower()
        pool = self.by_component.get(component, []) if component else self.events
        counts: dict[str, int] = defaultdict(int)
        for e in pool:
            if needle in e.message.lower():
                counts[e.component] += 1
        return dict(counts)

    def problem_events(self, start=None, end=None, min_severity="WARN") -> dict[str, list[LogEvent]]:
        floor = sev_rank(min_severity)
        out: dict[str, list[LogEvent]] = defaultdict(list)
        for e in self.events:
            if sev_rank(e.severity) < floor:
                continue
            if start and e.ts < start or end and e.ts > end:
                continue
            out[e.component].append(e)
        return dict(out)


def _compile_formats(formats: list) -> list:
    compiled = []
    for f in formats:
        rx = re.compile(f["regex"])
        needed = {"ts", "level", "message"}
        if not needed <= set(rx.groupindex):
            raise IngestError(f"format '{f.get('name')}' must define groups ts, level, message")
        compiled.append(rx)
    return compiled


def discover_files(cfg: LogsConfig) -> list[Path]:
    root = Path(cfg.root).resolve()
    if root.is_file():
        return [root]
    if not root.is_dir():
        raise IngestError(f"log root does not exist: {cfg.root}")
    found: dict[Path, None] = {}
    for pattern in cfg.include:
        for p in sorted(root.rglob(pattern)):
            try:
                r = p.resolve()
            except OSError:
                continue
            if not r.is_file():
                continue
            if not r.is_relative_to(root):          # symlink escaping the root
                continue
            found[r] = None
    return list(found)


def load_logs(cfg: LogsConfig, redact_enabled: bool = True) -> LogIndex:
    root = Path(cfg.root).resolve()
    base = root.parent if root.is_file() else root
    formats = _compile_formats(cfg.formats)
    events: list[LogEvent] = []
    stats = {"files": 0, "lines": 0, "parsed": 0, "unparsed": 0, "truncated_files": 0,
             "suspicious": 0}
    for path in discover_files(cfg):
        rel = path.relative_to(base).as_posix()
        stats["files"] += 1
        pending: Optional[dict] = None
        raw_events: list[dict] = []
        read_bytes = 0
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh, 1):
                read_bytes += len(line)
                if n > cfg.max_lines_per_file or read_bytes > cfg.max_bytes_per_file:
                    stats["truncated_files"] += 1
                    break
                stats["lines"] += 1
                line = line.rstrip("\r\n")
                if not line.strip():
                    continue
                m = None
                for rx in formats:
                    m = rx.match(line)
                    if m:
                        break
                if m:
                    try:
                        ts = parse_ts(m.group("ts"))
                    except ValueError:
                        m = None
                if m:
                    gd = m.groupdict()
                    pending = {"ts": ts, "level": norm_severity(gd["level"]),
                               "component": gd.get("component") or path.stem,
                               "message": gd["message"], "line_no": n}
                    raw_events.append(pending)
                    stats["parsed"] += 1
                elif pending is not None and line[:1].isspace():
                    if len(pending["message"]) < cfg.max_message_chars:
                        pending["message"] += " | " + line.strip()      # stack-trace continuation
                else:
                    stats["unparsed"] += 1
        for r in raw_events:
            msg = r["message"]
            if redact_enabled:
                msg = redact(msg)
            msg = sanitize(msg, cfg.max_message_chars)
            sus = looks_like_injection(msg)
            stats["suspicious"] += int(sus)
            events.append(LogEvent(
                uid=f"{rel}:{r['line_no']}", ts=r["ts"], severity=r["level"],
                component=r["component"], message=msg, source=rel,
                line_no=r["line_no"], suspicious=sus))
    if not events:
        raise IngestError("no log events could be parsed")
    return LogIndex(events, stats)


def event_line(e: LogEvent, evidence_id: str | None = None) -> str:
    prefix = f"[{evidence_id}] " if evidence_id else ""
    return f"{prefix}{fmt_ts(e.ts)} {e.severity} {e.component}: {e.message}"
