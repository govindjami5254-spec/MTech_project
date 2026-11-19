"""Read-only diagnostic tool registry.

Tools never touch the filesystem or network: they only query the in-memory LogIndex
built from the allowlisted log root. No tool accepts a path, a command or a regex.
"""
from __future__ import annotations

import time
from typing import Optional

from .config import AgentConfig
from .evidence import EvidenceStore, normalize_id
from .ingest import LogIndex, fmt_ts, parse_ts
from .models import Param, ToolDef, ToolResult
from .safety import AuditLog, PolicyViolation, ToolPolicy, wrap_untrusted

_SEV = ("DEBUG", "INFO", "WARN", "ERROR", "FATAL")

TOOL_DEFS: dict[str, ToolDef] = {
    "list_components": ToolDef(
        "list_components",
        "List all components (services) that have log events, with event counts.", ()),
    "error_timeline": ToolDef(
        "error_timeline",
        "Overview: for each component, its earliest WARN/ERROR/FATAL events in a time range. "
        "Good first step to see which component went wrong first.",
        (Param("start", "string", "ISO-8601 start time", is_time=True, maxlen=40),
         Param("end", "string", "ISO-8601 end time", is_time=True, maxlen=40),
         Param("min_severity", "string", "WARN, ERROR or FATAL (default WARN)", enum=("WARN", "ERROR", "FATAL")))),
    "search_logs": ToolDef(
        "search_logs",
        "Search events (earliest first). Filters are ANDed - prefer few filters and omit start/end unless needed. Filter by component, case-insensitive substring, "
        "minimum severity and time range. Returns citable evidence IDs.",
        (Param("component", "string", "component name", maxlen=64),
         Param("contains", "string", "case-insensitive substring (not a regex)", maxlen=80),
         Param("min_severity", "string", "minimum severity", enum=_SEV),
         Param("start", "string", "ISO-8601 start time", is_time=True, maxlen=40),
         Param("end", "string", "ISO-8601 end time", is_time=True, maxlen=40),
         Param("limit", "integer", "max events (1-25)", minimum=1, maximum=25))),
    "get_context": ToolDef(
        "get_context",
        "Show events (all components) just before/after an event you already have, by evidence ID.",
        (Param("evidence_id", "string", "evidence ID such as E3", required=True, maxlen=12),
         Param("before", "integer", "events before (0-10)", minimum=0, maximum=10),
         Param("after", "integer", "events after (0-10)", minimum=0, maximum=10))),
    "count_matches": ToolDef(
        "count_matches",
        "Count events containing a substring, per component. Counts are not citable evidence.",
        (Param("contains", "string", "case-insensitive substring", required=True, maxlen=80),
         Param("component", "string", "optional component filter", maxlen=64))),
}


def ollama_tool_specs(allowed: list[str]) -> list[dict]:
    specs = []
    for name in allowed:
        d = TOOL_DEFS.get(name)
        if not d:
            continue
        props, required = {}, []
        for p in d.params:
            prop = {"type": p.type, "description": p.description}
            if p.enum:
                prop["enum"] = list(p.enum)
            props[p.name] = prop
            if p.required:
                required.append(p.name)
        specs.append({"type": "function", "function": {
            "name": d.name, "description": d.description,
            "parameters": {"type": "object", "properties": props, "required": required}}})
    return specs


class ToolRegistry:
    def __init__(self, index: LogIndex, store: EvidenceStore, allowed: list[str],
                 cfg: AgentConfig, audit: AuditLog):
        self.index, self.store, self.cfg, self.audit = index, store, cfg, audit
        self.policy = ToolPolicy(TOOL_DEFS, allowed)
        self.allowed = allowed
        self.inspected: set[str] = set()      # components examined by an explicit tool call
        self.calls = 0
        self.blocked = 0

    def specs(self) -> list[dict]:
        return ollama_tool_specs(self.allowed)

    # ------------------------------------------------------------------ run
    def execute(self, name: str, args, step: int) -> ToolResult:
        t0 = time.monotonic()
        try:
            clean = self.policy.validate(name, args)
        except PolicyViolation as v:
            self.blocked += 1
            self.audit.log("tool_blocked", step=step, tool=name, args=_safe(args),
                           code=v.code, reason=v.message)
            return ToolResult(False, f"ERROR ({v.code}): {v.message}. Allowed tools: "
                                     f"{', '.join(self.allowed)}.", error_code=v.code)
        try:
            result = getattr(self, f"_t_{name}")(clean, step)
        except Exception as exc:                               # tool bug must not kill the run
            self.audit.log("tool_error", step=step, tool=name, args=clean, error=str(exc))
            return ToolResult(False, f"ERROR (tool_failed): {exc}", error_code="tool_failed")
        self.calls += 1
        text = result.text
        if len(text) > self.cfg.max_tool_output_chars:
            text = text[: self.cfg.max_tool_output_chars] + "\n...[output truncated]"
            result.text = text
        self.audit.log("tool_call", step=step, tool=name, args=clean,
                       evidence_ids=result.evidence_ids, output_chars=len(text),
                       ms=round((time.monotonic() - t0) * 1000, 1))
        for ev_id in result.evidence_ids:
            ev = self.store.get(ev_id)
            if ev and ev.suspicious:
                self.audit.log("injection_suspected", step=step, evidence_id=ev_id,
                               uid=ev.uid, tool=name)
        return result

    # ---------------------------------------------------------------- tools
    def _render(self, events, step, tool, header="") -> ToolResult:
        evs = self.store.add(events, step, tool)
        lines = [e.line() for e in evs]
        text = (header + "\n" if header else "") + (wrap_untrusted(lines) if lines else "(no matching events)")
        return ToolResult(True, text, [e.id for e in evs])

    def _t_list_components(self, a, step):
        rows = [f"{c}: {len(self.index.by_component[c])} events" for c in self.index.components]
        return ToolResult(True, "\n".join(rows))

    def _t_error_timeline(self, a, step):
        start = parse_ts(a["start"]) if "start" in a else None
        end = parse_ts(a["end"]) if "end" in a else None
        probs = self.index.problem_events(start, end, a.get("min_severity", "WARN"))
        ordered = sorted(probs.items(), key=lambda kv: kv[1][0].ts)
        events = []
        for _, evs in ordered:
            events.extend(evs[:2])                             # first two problem events per component
        events = events[: self.cfg.max_tool_output_events]
        events.sort(key=lambda e: (e.ts, e.source, e.line_no))
        return self._render(events, step, "error_timeline",
                            f"First problem events per component ({len(probs)} components with problems):")

    def _t_search_logs(self, a, step):
        comp = a.get("component")
        if comp and comp not in self.index.by_component:
            return ToolResult(False, f"ERROR (unknown_component): '{comp}'. Known: "
                                     f"{', '.join(self.index.components)}", error_code="unknown_component")
        limit = min(a.get("limit", 15), self.cfg.max_tool_output_events)
        events, total = self.index.search(
            comp, a.get("contains"), a.get("min_severity", "DEBUG"),
            parse_ts(a["start"]) if "start" in a else None,
            parse_ts(a["end"]) if "end" in a else None, limit)
        if comp:
            self.inspected.add(comp)
        note = f"{total} matching events" + (f", showing earliest {len(events)}" if total > len(events) else "")
        if total == 0 and len(a) > 1:
            note += (" (all filters are combined with AND - try fewer filters, e.g. only 'component' "
                     "and 'min_severity', and do not restrict start/end)")
        return self._render(events, step, "search_logs", note + ":")

    def _t_get_context(self, a, step):
        eid = normalize_id(a["evidence_id"])
        ev = self.store.get(eid) if eid else None
        if ev is None:
            return ToolResult(False, f"ERROR (unknown_evidence): '{a['evidence_id']}' was never returned "
                                     f"by a tool", error_code="unknown_evidence")
        events = self.index.context(ev.uid, a.get("before", 3), a.get("after", 3))
        self.inspected.add(ev.component)
        return self._render(events, step, "get_context", f"Context around {eid}:")

    def _t_count_matches(self, a, step):
        comp = a.get("component")
        if comp and comp not in self.index.by_component:
            return ToolResult(False, f"ERROR (unknown_component): '{comp}'", error_code="unknown_component")
        counts = self.index.count(a["contains"], comp)
        if not counts:
            return ToolResult(True, "0 matches")
        rows = [f"{c}: {n}" for c, n in sorted(counts.items(), key=lambda kv: -kv[1])]
        return ToolResult(True, "Matches per component:\n" + "\n".join(rows))


def _safe(args) -> str:
    try:
        return str(args)[:300]
    except Exception:
        return "<unprintable>"
