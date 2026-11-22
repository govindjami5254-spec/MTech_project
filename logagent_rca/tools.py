"""Read-only diagnostic tools for E3 (M6).

Tools query only the in-memory LogIndex of the current case. Every event a tool returns goes through
the shared EvidenceLedger (strict B, ``stop_on_overflow=True``):
* new events are charged and shown in full canonical form;
* already-shown events are free and shown as a compact reference ``[E3] (already shown)``;
* once B is exhausted the tool says so and returns no further new evidence.
Framing text contains no counts or other log-derived aggregates, so all source-derived content the
model sees is charged evidence. Tools that would reveal aggregates (counts) are deliberately absent.
"""
from __future__ import annotations

import time
from typing import Optional

from .config import SafetyConfig
from .context import CaseContext
from .evidence import BLOCK_CLOSE, BLOCK_OPEN, EvidenceLedger, render_evidence
from .ingest import parse_ts
from .schemas import Severity, ToolCallRecord
from .safety import SEVERITIES, AuditLog, Param, PolicyViolation, ToolPolicy, ToolSpec

TOOL_SPECS: dict[str, ToolSpec] = {
    "error_timeline": ToolSpec(
        "error_timeline",
        "Earliest problem events (WARN or worse) of each component, oldest first. Good first step.",
        (Param("min_severity", "string", "WARN, ERROR or FATAL (default WARN)", enum=("WARN", "ERROR", "FATAL")),
         Param("start", "string", "optional ISO-8601 start time", is_time=True, maxlen=40),
         Param("end", "string", "optional ISO-8601 end time", is_time=True, maxlen=40))),
    "search_logs": ToolSpec(
        "search_logs",
        "Events of one component (or all), oldest first, filtered by minimum severity and an optional "
        "case-insensitive substring. Filters are combined with AND; use few filters.",
        (Param("component", "string", "component name"),
         Param("contains", "string", "case-insensitive substring (not a regex)", maxlen=80),
         Param("min_severity", "string", "minimum severity (default DEBUG)", enum=SEVERITIES),
         Param("start", "string", "optional ISO-8601 start time", is_time=True, maxlen=40),
         Param("end", "string", "optional ISO-8601 end time", is_time=True, maxlen=40),
         Param("limit", "integer", "maximum events, 1-15 (default 10)", minimum=1, maximum=15))),
    "get_context": ToolSpec(
        "get_context",
        "Events from all components immediately before and after an evidence item you already have.",
        (Param("evidence_id", "string", "evidence ID such as E3", required=True, maxlen=12),
         Param("before", "integer", "events before, 0-8 (default 3)", minimum=0, maximum=8),
         Param("after", "integer", "events after, 0-8 (default 3)", minimum=0, maximum=8))),
}


class ToolRegistry:
    def __init__(self, ctx: CaseContext, ledger: EvidenceLedger, safety: SafetyConfig, audit: AuditLog,
                 lookback_s: int):
        self.ctx, self.ledger, self.cfg, self.audit = ctx, ledger, safety, audit
        self.policy = ToolPolicy(TOOL_SPECS, safety.allowed_tools)
        self.start, self.end = ctx.window(lookback_s)
        self.inspected: set[str] = {ctx.trigger.component}     # components the agent explicitly examined
        self.records: list[ToolCallRecord] = []
        self.calls = 0
        self.blocked = 0

    def specs(self) -> list[dict]:
        return [TOOL_SPECS[n].ollama() for n in self.cfg.allowed_tools if n in TOOL_SPECS]

    # ------------------------------------------------------------------ dispatch
    def execute(self, name, args, step: int) -> str:
        t0 = time.monotonic()
        try:
            clean = self.policy.validate(name, args)
        except PolicyViolation as v:
            self.blocked += 1
            self.audit.log("tool_blocked", step=step, tool=str(name)[:80], args=str(args)[:300],
                           code=v.code, reason=v.message)
            self.records.append(ToolCallRecord(step=step, tool=str(name)[:80], args=_safe_args(args),
                                               allowed=False, error_code=v.code))
            return f"ERROR ({v.code}): {v.message}. Allowed tools: {', '.join(self.cfg.allowed_tools)}."
        events, note = getattr(self, f"_t_{name}")(clean)
        res = self.ledger.offer(events, step, name, stop_on_overflow=True)
        lines = []
        new = {e.uid for e in res.added}
        for e in res.shown:
            lines.append(render_evidence(e.id, e) if e.uid in new else f"[{e.id}] (already shown)")
        parts = [note] if note else []
        parts.append(BLOCK_OPEN + "\n" + "".join(l + "\n" for l in lines) + BLOCK_CLOSE if lines
                     else "(no new matching events)")
        if res.budget_exhausted:
            parts.append("(evidence budget exhausted: further new events cannot be shown)")
        text = "\n".join(parts)[: self.cfg.max_tool_output_chars]
        self.calls += 1
        rec = ToolCallRecord(step=step, tool=name, args=clean, allowed=True,
                             evidence_ids=[e.id for e in res.shown], new_evidence_tokens=res.tokens_added,
                             output_chars=len(text), ms=round((time.monotonic() - t0) * 1000, 2))
        self.records.append(rec)
        self.audit.log("tool_call", step=step, tool=name, args=clean, new_ids=[e.id for e in res.added],
                       repeated_ids=[e.id for e in res.repeated], new_tokens=res.tokens_added,
                       budget_used=self.ledger.used, budget_exhausted=res.budget_exhausted)
        for e in res.added:
            if e.suspicious:
                self.audit.log("injection_suspected", step=step, tool=name, evidence_id=e.id, uid=e.uid)
        return text

    # ------------------------------------------------------------------ tools
    def _times(self, a):
        s = parse_ts(a["start"]) if "start" in a else self.start
        e = parse_ts(a["end"]) if "end" in a else self.end
        return s, e

    def _t_error_timeline(self, a):
        s, e = self._times(a)
        probs = self.ctx.index.problem_events(s, e, a.get("min_severity", "WARN"))
        events = [ev for evs in probs.values() for ev in evs[:2]][: self.cfg.max_tool_output_events]
        events.sort(key=lambda x: (x.ts, x.source, x.line_no))
        return events, "Earliest problem events per component:"

    def _t_search_logs(self, a):
        comp = a.get("component")
        if comp and comp not in self.ctx.index.components:
            return [], f"Unknown component {comp!r}. Known: {', '.join(self.ctx.index.components)}."
        s, e = self._times(a)
        hits, _ = self.ctx.index.search(comp, a.get("contains"), a.get("min_severity", "DEBUG"), s, e,
                                        min(a.get("limit", 10), self.cfg.max_tool_output_events))
        if comp:
            self.inspected.add(comp)
        return hits, None

    def _t_get_context(self, a):
        raw = a["evidence_id"].strip().strip("[]").upper()
        item = self.ledger.get(raw)
        if item is None:
            return [], f"Unknown evidence ID {a['evidence_id']!r}: use an ID returned earlier."
        self.inspected.add(item.component)
        return self.ctx.index.context(item.uid, a.get("before", 3), a.get("after", 3)), f"Context around {raw}:"


def _safe_args(args) -> dict:
    if isinstance(args, dict):
        return {str(k)[:40]: str(v)[:100] for k, v in list(args.items())[:10]}
    return {"_raw": str(args)[:100]}
