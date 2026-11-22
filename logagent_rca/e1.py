"""E1: rule-based RCA (M4). No LLM. Rules were written against the DEVELOPMENT split only.

Rules:
1. Start at the incident component. Among its WARN+ events in the analysis window, find the most
   frequently mentioned *other known component* (whole-word match). Follow it; repeat until a
   component mentions no further dependency (or a cycle).
2. The terminal component is the root cause. If it is not the starting component and has no
   ERROR/FATAL events of its own, the dependency looks silent: report insufficient evidence.
3. Fault type from keyword rules (dev vocabulary only), for the summary text.
The evidence it cites goes through the same ledger and budget B as the LLM arms.

E1f (floor): ignores the logs and names the incident component itself, citing only the trigger.
"""
from __future__ import annotations

import re
from collections import Counter

from .context import ArmResult, CaseContext
from .evidence import EvidenceLedger
from .schemas import Claim, FinalReport, Hypothesis, LogEvent, Severity
from .tokens import TokenCounter

FAULT_KEYWORDS = (           # authored from dev_templates only
    ("disk full", ("no space", "disk usage", "filesystem", "full")),
    ("out of memory", ("outofmemory", "out of memory", "heap", "oom")),
    ("invalid configuration", ("config",)),
    ("connection pool exhausted", ("pool",)),
)


def _mentions(text: str, names: list[str]) -> list[str]:
    return [n for n in names if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(n)}(?![A-Za-z0-9_-])", text)]


def _fault_label(events: list[LogEvent]) -> str:
    text = " ".join(e.message.lower() for e in events)
    for label, words in FAULT_KEYWORDS:
        if any(w in text for w in words):
            return label
    return "unclassified failure"


def _short(text: str, n: int = 200) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def run_e1(ctx: CaseContext, counter: TokenCounter, budget: int, lookback_s: int) -> ArmResult:
    ledger = EvidenceLedger(budget, counter)
    ledger.offer([ctx.trigger], 0, "incident", stop_on_overflow=False)
    start, end = ctx.window(lookback_s)
    names = ctx.index.components

    def problems(comp, floor=Severity.WARN):
        return ctx.index.search(component=comp, min_severity=floor, start=start, end=end, limit=10_000)[0]

    chain, hops = [ctx.trigger.component], []
    while True:
        cur = chain[-1]
        counts, first = Counter(), {}
        for e in problems(cur):
            for dep in _mentions(e.message, [n for n in names if n != cur]):
                counts[dep] += 1
                first.setdefault(dep, e)
        if not counts:
            break
        nxt = max(counts, key=lambda d: (counts[d], -first[d].ts.timestamp()))
        if nxt in chain:
            break
        hops.append((cur, nxt, first[nxt]))
        chain.append(nxt)

    cause = chain[-1]
    own_errors = problems(cause, Severity.ERROR)
    silent = cause != chain[0] and not own_errors
    hop_events = [ev for _, _, ev in hops]
    cause_events = problems(cause)[:3]
    ledger.offer(hop_events + cause_events, 1, "e1_rules", stop_on_overflow=False)
    label = {e.uid: e.id for e in ledger.items()}

    claims = []
    for caller, dep, ev in hops[-3:]:
        if ev.uid in label:
            claims.append(Claim(text=_short(f"{caller} reported failures calling {dep}: {ev.message}"),
                                evidence_ids=[label[ev.uid]]))
    if silent:
        report = FinalReport(insufficient_evidence=True, hypotheses=[], recommendations=[],
                             evidence_gaps=[_short(f"{cause} is blamed by its callers but logs no errors "
                                                   f"itself; the cause is not visible in the logs")])
        return ArmResult(report, ledger, notes={"chain": chain, "rule": "silent_dependency"})
    cited = [label[e.uid] for e in cause_events if e.uid in label]
    if cited:
        claims.append(Claim(text=_short(f"{cause} logged its own failure: {cause_events[-1].message}"),
                            evidence_ids=cited[:5]))
    if not claims:
        claims = [Claim(text=_short(f"{cause} reported: {ctx.trigger.message}"), evidence_ids=["E1"])]
    hyp = Hypothesis(cause_component=cause, confidence=0.6, claims=claims[-4:],
                     cause_summary=_short(f"{_fault_label(cause_events)} in {cause} "
                                          f"(dependency chain: {' -> '.join(chain)})"))
    report = FinalReport(insufficient_evidence=False, hypotheses=[hyp], evidence_gaps=[],
                         recommendations=[_short(f"Inspect {cause} for {_fault_label(cause_events)}.")])
    return ArmResult(report, ledger, notes={"chain": chain, "rule": "dependency_chain"})


def run_e1_floor(ctx: CaseContext, counter: TokenCounter, budget: int) -> ArmResult:
    ledger = EvidenceLedger(budget, counter)
    ledger.offer([ctx.trigger], 0, "incident", stop_on_overflow=False)
    comp = ctx.trigger.component
    hyp = Hypothesis(cause_component=comp, confidence=0.1, cause_summary=_short(f"{comp} reported the incident"),
                     claims=[Claim(text=_short(f"{comp} returned errors: {ctx.trigger.message}"),
                                   evidence_ids=["E1"])])
    return ArmResult(FinalReport(insufficient_evidence=False, hypotheses=[hyp], evidence_gaps=[],
                                 recommendations=[]), ledger, notes={"rule": "log_free_floor"})
