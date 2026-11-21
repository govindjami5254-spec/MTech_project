"""Canonical evidence rendering and the strict evidence-token ledger (M2).

One ledger is used by E2b (packing) and E3 (tool results), so both arms are charged identically:

* Every source-derived item shown to a model is rendered by ``render_evidence`` (citation label,
  timestamp, severity, component, source:line, message) and charged ``count(render + "\\n")``
  tokens: the item text plus its newline separator. Block framing (``<log_data>`` tags, headers)
  and the incident header are *prompt overhead*, not evidence.
* The stable identity of an item is its event uid (``source:line``). Each uid is charged once per
  run, when first presented; its citation label (``E<n>``) is assigned once and never changes.
* Re-presenting an item costs nothing against B but is recorded as repeated exposure (compute cost).
* B is strict: an item is admitted only if ``used + cost <= B``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .schemas import Evidence, LogEvent
from .tokens import TokenCounter

BLOCK_OPEN = "<log_data>"
BLOCK_CLOSE = "</log_data>"


def _fmt_ts(e) -> str:
    return e.ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def render_evidence(label: str, event: LogEvent | Evidence) -> str:
    """Canonical single-line representation of one evidence item (exactly what the model sees)."""
    return (f"[{label}] {_fmt_ts(event)} {event.severity.value} {event.component} "
            f"({event.source}:{event.line_no}) {event.message}")


def render_block(items: Iterable[Evidence]) -> str:
    """Evidence block inserted into prompts: framing + one canonical line per item."""
    lines = [render_evidence(e.id, e) for e in items]
    return BLOCK_OPEN + "\n" + "".join(line + "\n" for line in lines) + BLOCK_CLOSE


@dataclass
class OfferResult:
    added: list[Evidence] = field(default_factory=list)       # newly admitted (charged)
    repeated: list[Evidence] = field(default_factory=list)    # already admitted (free, recorded)
    rejected: list[LogEvent] = field(default_factory=list)    # would exceed B
    shown: list[Evidence] = field(default_factory=list)       # rendered back, in offer order
    tokens_added: int = 0
    budget_exhausted: bool = False


class EvidenceLedger:
    def __init__(self, budget: int, counter: TokenCounter):
        if budget < 1:
            raise ValueError("budget must be >= 1")
        self.budget = budget
        self._counter = counter
        self._by_uid: dict[str, Evidence] = {}
        self._order: list[str] = []
        self.used = 0
        self.repeated_exposures = 0
        self.repeated_tokens = 0
        self.rejected_items = 0

    # ---------------------------------------------------------------- costing
    def _next_label(self) -> str:
        return f"E{len(self._order) + 1}"

    def cost_of(self, event: LogEvent, label: str | None = None) -> int:
        return self._counter.count(render_evidence(label or self._next_label(), event) + "\n")

    @property
    def remaining(self) -> int:
        return self.budget - self.used

    # ---------------------------------------------------------------- offering
    def offer(self, events: Iterable[LogEvent], step: int, tool: str,
              stop_on_overflow: bool = True) -> OfferResult:
        """Admit events in order under the strict budget.

        ``stop_on_overflow=True`` (tool results): stop at the first item that does not fit,
        preserving order. ``False`` (single-pass packing): skip it and keep trying later items.
        Duplicates within one offer are collapsed.
        """
        res = OfferResult()
        seen_in_offer: set[str] = set()
        stopped = False
        for ev in events:
            if ev.uid in seen_in_offer:
                continue
            seen_in_offer.add(ev.uid)
            known = self._by_uid.get(ev.uid)
            if known is not None:
                self.repeated_exposures += 1
                self.repeated_tokens += self._counter.count(render_evidence(known.id, known) + "\n")
                res.repeated.append(known)
                res.shown.append(known)
                continue
            if stopped:
                res.rejected.append(ev)
                continue
            label = self._next_label()
            cost = self.cost_of(ev, label)
            if self.used + cost > self.budget:
                res.rejected.append(ev)
                res.budget_exhausted = True
                if stop_on_overflow:
                    stopped = True
                continue
            item = Evidence(id=label, uid=ev.uid, ts=ev.ts, severity=ev.severity,
                            component=ev.component, source=ev.source, line_no=ev.line_no,
                            message=ev.message, step=step, tool=tool, tokens=cost,
                            suspicious=ev.suspicious)
            self._by_uid[ev.uid] = item
            self._order.append(ev.uid)
            self.used += cost
            res.added.append(item)
            res.shown.append(item)
            res.tokens_added += cost
        self.rejected_items += len(res.rejected)
        return res

    # ---------------------------------------------------------------- access
    def items(self) -> list[Evidence]:
        return [self._by_uid[u] for u in self._order]

    def get(self, label: str) -> Evidence | None:
        for e in self._by_uid.values():
            if e.id == label:
                return e
        return None

    def has_uid(self, uid: str) -> bool:
        return uid in self._by_uid

    def summary(self) -> dict:
        """Fields that feed ``RunMetrics`` and the compute-cost report."""
        return {"evidence_token_budget": self.budget, "unique_evidence_tokens": self.used,
                "unique_evidence_items": len(self._order),
                "repeated_exposures": self.repeated_exposures,
                "repeated_exposure_tokens": self.repeated_tokens,
                "rejected_items": self.rejected_items}
