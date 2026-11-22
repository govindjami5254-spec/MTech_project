"""E2b: strong single-pass LLM (M5). One evidence pack under B, one final call (plus one retry)."""
from __future__ import annotations

from .config import Config
from .context import ArmResult, CaseContext, LLMUsage
from .evidence import EvidenceLedger, render_block
from .extract import pack
from .finalize import request_final
from .prompts import SYSTEM_PROMPT, incident_header
from .schemas import RunStatus
from .tokens import TokenCounter


def run_e2b(ctx: CaseContext, cfg: Config, llm, counter: TokenCounter, seed: int) -> ArmResult:
    ledger = EvidenceLedger(cfg.budget.evidence_token_budget, counter)
    items = pack(ctx, ledger, cfg.agent.lookback_s)
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"{incident_header(ctx)}\n\nEvidence (cite these IDs):\n"
                                            f"{render_block(items)}"}]
    usage = LLMUsage()
    report, error = request_final(llm, messages, seed, usage, cfg.llm.max_parse_retries)
    return ArmResult(report_raw=report, ledger=ledger, llm=usage,
                     status=RunStatus.OK if report else RunStatus.FAILED, error=error, steps=1,
                     notes={"packed_items": len(items), "messages": messages})
