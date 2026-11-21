"""Read-only, time-ordered index over one case's log events (M2)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable, Optional

from .schemas import LogEvent, Severity, normalize_severity


class LogIndex:
    def __init__(self, events: Iterable[LogEvent]):
        evs = sorted(events, key=lambda e: (e.ts, e.source, e.line_no))
        if len({e.uid for e in evs}) != len(evs):
            raise ValueError("duplicate event uid in index")
        self._events: tuple[LogEvent, ...] = tuple(evs)
        self._pos = {e.uid: i for i, e in enumerate(self._events)}
        by = defaultdict(list)
        for e in self._events:
            by[e.component].append(e)
        self._by_component = {c: tuple(v) for c, v in by.items()}

    def __len__(self) -> int:
        return len(self._events)

    @property
    def events(self) -> tuple[LogEvent, ...]:
        return self._events

    @property
    def components(self) -> list[str]:
        return sorted(self._by_component)

    def component_counts(self) -> dict[str, int]:
        return {c: len(v) for c, v in sorted(self._by_component.items())}

    def get(self, uid: str) -> Optional[LogEvent]:
        i = self._pos.get(uid)
        return self._events[i] if i is not None else None

    def search(self, component: Optional[str] = None, contains: Optional[str] = None,
               min_severity: Severity | str = Severity.DEBUG, start: Optional[datetime] = None,
               end: Optional[datetime] = None, limit: int = 25) -> tuple[list[LogEvent], int]:
        """Earliest-first matches and the total match count (before ``limit``)."""
        pool = self._by_component.get(component, ()) if component else self._events
        needle = contains.casefold() if contains else None
        floor = normalize_severity(min_severity).rank
        hits = [e for e in pool
                if e.severity.rank >= floor
                and (start is None or e.ts >= start) and (end is None or e.ts <= end)
                and (needle is None or needle in e.message.casefold())]
        return hits[:max(0, limit)], len(hits)

    def context(self, uid: str, before: int = 3, after: int = 3) -> list[LogEvent]:
        i = self._pos.get(uid)
        if i is None:
            return []
        return list(self._events[max(0, i - before): i + after + 1])

    def count(self, contains: str, component: Optional[str] = None) -> dict[str, int]:
        needle = contains.casefold()
        pool = self._by_component.get(component, ()) if component else self._events
        out: dict[str, int] = defaultdict(int)
        for e in pool:
            if needle in e.message.casefold():
                out[e.component] += 1
        return dict(sorted(out.items()))

    def problem_events(self, start: Optional[datetime] = None, end: Optional[datetime] = None,
                       min_severity: Severity | str = Severity.WARN) -> dict[str, list[LogEvent]]:
        """WARN+ events per component, components ordered by their first problem."""
        floor = normalize_severity(min_severity).rank
        out: dict[str, list[LogEvent]] = {}
        for e in self._events:
            if e.severity.rank >= floor and (start is None or e.ts >= start) and (end is None or e.ts <= end):
                out.setdefault(e.component, []).append(e)
        return out
