"""E3: iterative evidence collection with read-only tools (M7), coverage gate hook (M8).

Controller rules (code, not prompt):
* at most ``max_steps`` model turns (extended only by the coverage gate), ``max_run_seconds`` wall
  time and ``max_blocked_calls`` refused tool requests;
* at most 3 tool calls are executed per turn;
* the agent may not finish before ``min_tool_calls`` successful tool calls;
* the final answer uses the shared final instruction and JSON schema (identical to E2b), appended to
  the same conversation, so the final call sees the evidence plus the investigation trace.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from .config import Config
from .context import ArmResult, CaseContext, LLMUsage
from .evidence import EvidenceLedger, render_block
from .finalize import request_final
from .llm import LLMError
from .prompts import SYSTEM_PROMPT, incident_header
from .safety import AuditLog
from .schemas import RunStatus
from .tokens import TokenCounter
from .tools import ToolRegistry

MAX_CALLS_PER_TURN = 3

INVESTIGATE = """Investigate the root cause with the read-only tools before answering.
- Start with error_timeline, then look at the components that failed first or that others depend on.
- Each new evidence line costs part of a fixed evidence budget of {budget} tokens ({remaining} left); lines you already saw are free.
- When you have enough evidence, reply with the single word DONE (no tool call)."""

# A gate returns a message forcing more investigation, or None to allow finishing.
Gate = Callable[[ToolRegistry, int], Optional[str]]


def run_e3(ctx: CaseContext, cfg: Config, llm, counter: TokenCounter, seed: int, audit: AuditLog,
           gate: Optional[Gate] = None) -> ArmResult:
    ag = cfg.agent
    ledger = EvidenceLedger(cfg.budget.evidence_token_budget, counter)
    ledger.offer([ctx.trigger], 0, "incident", stop_on_overflow=False)
    tools = ToolRegistry(ctx, ledger, cfg.safety, audit, ag.lookback_s)
    usage = LLMUsage()
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"{incident_header(ctx)}\n\nIncident trigger:\n"
                 f"{render_block(ledger.items())}\n\n"
                 + INVESTIGATE.format(budget=ledger.budget, remaining=ledger.remaining)}]
    audit.log("e3_start", case=ctx.manifest.case_id, budget=ledger.budget, max_steps=ag.max_steps,
              coverage_gate=gate is not None)
    deadline = time.monotonic() + ag.max_run_seconds
    allowed, step, gate_rounds, aborted = ag.max_steps, 0, 0, None
    while True:
        if step >= allowed:
            msg = gate(tools, step) if gate and gate_rounds < ag.max_gate_rounds else None
            if msg:
                gate_rounds += 1
                allowed = step + ag.gate_extra_steps
                messages.append({"role": "user", "content": msg})
                audit.log("coverage_gate", step=step, round=gate_rounds, reason="step_budget")
                continue
            break
        if time.monotonic() > deadline:
            aborted = "time_budget"
            break
        if tools.blocked >= ag.max_blocked_calls:
            aborted = "too_many_blocked_calls"
            break
        step += 1
        try:
            resp = llm.chat(messages, seed=seed + step, tools=tools.specs())
        except LLMError as exc:
            aborted = f"llm_error: {str(exc)[:200]}"
            break
        usage.calls += 1
        usage.prompt_tokens += resp.prompt_tokens
        usage.output_tokens += resp.output_tokens
        usage.seconds += resp.seconds
        messages.append(resp.as_message())
        if resp.tool_calls:
            for i, tc in enumerate(resp.tool_calls):
                if i >= MAX_CALLS_PER_TURN:
                    messages.append({"role": "tool", "tool_name": str(tc.name)[:40],
                                     "content": "Not executed: at most 3 tool calls per turn."})
                    continue
                out = tools.execute(tc.name, tc.args, step)
                messages.append({"role": "tool", "tool_name": str(tc.name)[:40], "content": out})
            continue
        if tools.calls < ag.min_tool_calls:
            audit.log("controller_nudge", step=step, reason="min_tool_calls")
            messages.append({"role": "user", "content": f"Gather evidence with the tools first (at least "
                             f"{ag.min_tool_calls} tool calls). Start with error_timeline."})
            continue
        msg = gate(tools, step) if gate and gate_rounds < ag.max_gate_rounds else None
        if msg:
            gate_rounds += 1
            allowed = max(allowed, step + ag.gate_extra_steps)
            messages.append({"role": "user", "content": msg})
            audit.log("coverage_gate", step=step, round=gate_rounds, reason="agent_finished")
            continue
        break
    if aborted:
        audit.log("e3_aborted", reason=aborted)
    report, error = request_final(llm, messages, seed + 100, usage, cfg.llm.max_parse_retries)
    status = RunStatus.OK if report else RunStatus.FAILED
    if aborted and aborted.startswith("llm_error") and report is None:
        status = RunStatus.ABORTED
    audit.log("e3_end", steps=step, tool_calls=tools.calls, blocked=tools.blocked, gate_rounds=gate_rounds,
              evidence=ledger.summary(), status=status.value)
    return ArmResult(report_raw=report, ledger=ledger, status=status, error=error or aborted,
                     tool_calls=tools.records, llm=usage, steps=step, gate_rounds=gate_rounds,
                     blocked_calls=tools.blocked,
                     notes={"aborted": aborted, "inspected": sorted(tools.inspected), "messages": messages})
