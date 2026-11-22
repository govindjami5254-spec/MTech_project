"""Deterministic evidence extraction, ranking and packing for the strong single pass E2b (M5).

Log-Insight-style reduction without an LLM:
1. Candidates: events in the analysis window (lookback before the incident, short margin after).
2. Template clustering: digits and hex identifiers are masked; each (component, template) group is a
   pattern. Floods of repeated errors collapse into one pattern.
3. Ranking: WARN+ patterns first, ordered by severity, then by first occurrence (earliest first, since
   causes precede symptoms); then INFO patterns from components that had problems, earliest first.
4. Packing: the first instance of each pattern is offered, in rank order, to the shared ledger with
   ``stop_on_overflow=False``, so oversized items are skipped and smaller ones still fit under B.
The prompt then lists the packed evidence chronologically.
"""
from __future__ import annotations

import re

from .context import CaseContext
from .evidence import EvidenceLedger
from .schemas import Evidence, LogEvent, Severity

_MASK = re.compile(r"0x[0-9a-fA-F]+|\b[0-9a-f]{6,}\b|\d+")


def template(msg: str) -> str:
    return _MASK.sub("#", msg)


def rank_candidates(ctx: CaseContext, lookback_s: int) -> list[LogEvent]:
    start, end = ctx.window(lookback_s)
    pool, _ = ctx.index.search(start=start, end=end, limit=10**9)
    groups: dict[tuple, list[LogEvent]] = {}
    for e in pool:
        groups.setdefault((e.component, template(e.message)), []).append(e)
    firsts = [g[0] for g in groups.values()]
    problem_comps = {e.component for e in firsts if e.severity.rank >= Severity.WARN.rank}
    warn = sorted((e for e in firsts if e.severity.rank >= Severity.WARN.rank),
                  key=lambda e: (-e.severity.rank, e.ts, e.source, e.line_no))
    info = sorted((e for e in firsts if e.severity.rank < Severity.WARN.rank and e.component in problem_comps),
                  key=lambda e: (e.ts, e.source, e.line_no))
    return warn + info


def pack(ctx: CaseContext, ledger: EvidenceLedger, lookback_s: int) -> list[Evidence]:
    ledger.offer([ctx.trigger], 0, "incident", stop_on_overflow=False)
    ledger.offer(rank_candidates(ctx, lookback_s), 0, "e2b_pack", stop_on_overflow=False)
    return sorted(ledger.items(), key=lambda e: (e.ts, e.source, e.line_no))
