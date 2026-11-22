"""Coverage gate (M8): code-level enforcement against incomplete exploration.

When the agent tries to finish (or runs out of steps), the controller lists components that logged
WARN+ events in the lookback window *before* the incident and that the agent never explicitly
examined (``search_logs`` with that component, or ``get_context`` on one of its evidence items).
If any exist, finishing is refused and the agent is told which ones to inspect. The gate is limited
to ``max_gate_rounds`` rounds, each adding ``gate_extra_steps`` steps, and stays silent once the
evidence budget is (nearly) exhausted, since further inspection could not show new evidence.

A2 runs E3 with this gate disabled.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from .tools import ToolRegistry

MIN_REMAINING_TOKENS = 60          # below this, no new evidence line could fit


def pending_components(tools: ToolRegistry, lookback_s: int) -> list[tuple[str, str]]:
    inc = tools.ctx.manifest.incident.ts
    probs = tools.ctx.index.problem_events(inc - timedelta(seconds=lookback_s), inc, "WARN")
    out = [(evs[0].ts, c) for c, evs in probs.items() if c not in tools.inspected]
    out.sort()
    return [(c, ts.strftime("%Y-%m-%dT%H:%M:%SZ")) for ts, c in out]


def make_gate(lookback_s: int, max_listed: int = 3):
    def gate(tools: ToolRegistry, step: int) -> Optional[str]:
        if tools.ledger.remaining < MIN_REMAINING_TOKENS:
            tools.audit.log("coverage_gate_skipped", step=step, reason="budget_exhausted")
            return None
        pend = pending_components(tools, lookback_s)
        if not pend:
            return None
        names = ", ".join(f"{c} (first problem at {ts})" for c, ts in pend[:max_listed])
        tools.audit.log("coverage_gate_pending", step=step, pending=[c for c, _ in pend])
        return (f"Not finished yet: these components logged WARN/ERROR events before the incident and you "
                f"have not examined them: {names}. Inspect each with search_logs (component=...) or "
                f"get_context, then reply DONE.")
    return gate
