"""M5 tests: extraction/packing, shared final call, E2b with a scripted LLM, resource sampler."""
import json
from pathlib import Path

import pytest

from logagent_rca.config import load_config
from logagent_rca.context import LLMUsage, open_case
from logagent_rca.e2b import run_e2b
from logagent_rca.evidence import EvidenceLedger
from logagent_rca.extract import pack, rank_candidates, template
from logagent_rca.finalize import request_final
from logagent_rca.llm import LLMResponse, ScriptedLLM
from logagent_rca.prompts import FINAL_INSTRUCTION, FINAL_SCHEMA, SYSTEM_PROMPT
from logagent_rca.resources import ResourceSampler
from logagent_rca.schemas import RunStatus, Severity
from logagent_rca.tokens import counter_from_config
from logagent_rca.truth import TruthStore

ROOT = Path(__file__).resolve().parent.parent
CFG = load_config(ROOT / "configs" / "dev.yaml")
COUNTER = counter_from_config(CFG.budget)
STORE = TruthStore(CFG.data.truth_dir)
B = CFG.budget.evidence_token_budget


def _ctx(stratum):
    cid = next(c for c in STORE.case_ids() if STORE.load(c).stratum.value == stratum)
    return open_case(CFG.data.cases_path / cid, CFG), STORE.load(cid)


GOOD = json.dumps({"insufficient_evidence": False, "hypotheses": [{
    "cause_component": "posting-svc", "cause_summary": "pool exhausted", "confidence": 0.7,
    "claims": [{"text": "posting-svc pool exhausted", "evidence_ids": ["E2"]}]}],
    "evidence_gaps": [], "recommendations": []})


def test_template_masks_ids_and_numbers():
    assert template("rid=9cefdd60 took 120ms") == template("rid=0011aabb took 95ms") == "rid=# took #ms"


def test_packing_is_within_budget_and_keeps_root_cause_in_over_budget_case():
    ctx, truth = _ctx("over_budget")
    led = EvidenceLedger(B, COUNTER)
    items = pack(ctx, led, CFG.agent.lookback_s)
    assert led.used <= B and items[0].ts <= items[-1].ts
    assert items[0].uid == ctx.trigger.uid or any(e.uid == ctx.trigger.uid for e in items)
    assert set(truth.key_evidence) & {e.uid for e in items}, "root-cause line must survive packing"
    packed = [(e.component, template(e.message)) for e in items if e.tool == "e2b_pack"]
    assert len(packed) == len(set(packed)), "one instance per (component, template) pattern"


def test_ranking_puts_warn_plus_before_info():
    ctx, _ = _ctx("easy")
    ranked = rank_candidates(ctx, CFG.agent.lookback_s)
    sev = [e.severity.rank >= Severity.WARN.rank for e in ranked]
    assert sev == sorted(sev, reverse=True)


def test_request_final_parses_and_retries_once():
    calls = iter([LLMResponse(content="not json"), LLMResponse(content=GOOD, prompt_tokens=50, output_tokens=20)])
    llm = ScriptedLLM(lambda m, t, s: next(calls))
    usage = LLMUsage()
    msgs = [{"role": "user", "content": "x"}]
    report, err = request_final(llm, msgs, 1, usage, max_retries=1)
    assert report.hypotheses[0].cause_component == "posting-svc" and err is None
    assert usage.parse_failures == 1 and usage.calls == 2 and usage.prompt_tokens == 50
    assert llm.calls[0][-1]["content"] == FINAL_INSTRUCTION


def test_request_final_gives_up_after_retries():
    llm = ScriptedLLM(lambda m, t, s: LLMResponse(content="{}"))
    report, err = request_final(llm, [{"role": "user", "content": "x"}], 1, LLMUsage(), max_retries=1)
    assert report is None and "invalid final report" in err


def test_e2b_uses_shared_prompt_schema_and_budget():
    ctx, _ = _ctx("over_budget")
    seen = {}

    def script(messages, tools, schema):
        seen.update(messages=messages, tools=tools, schema=schema)
        return LLMResponse(content=GOOD)

    r = run_e2b(ctx, CFG, ScriptedLLM(script), COUNTER, seed=7)
    assert r.status == RunStatus.OK and r.ledger.used <= B and r.steps == 1
    assert seen["tools"] is None and seen["schema"] == FINAL_SCHEMA
    assert seen["messages"][0]["content"] == SYSTEM_PROMPT and "<log_data>" in seen["messages"][1]["content"]
    assert seen["messages"][-1]["content"] == FINAL_INSTRUCTION


def test_e2b_failure_is_recorded_not_raised():
    ctx, _ = _ctx("easy")
    r = run_e2b(ctx, CFG, ScriptedLLM(lambda m, t, s: LLMResponse(content="garbage")), COUNTER, seed=1)
    assert r.status == RunStatus.FAILED and r.report_raw is None and r.llm.parse_failures == 2


def test_resource_sampler_runs():
    with ResourceSampler(interval=0.1) as s:
        sum(range(10**6))
    assert s.cpu_seconds is not None and s.cpu_seconds >= 0


def test_normalise_truncates_identically_and_counts():
    from logagent_rca.finalize import normalise
    long = {"insufficient_evidence": False, "evidence_gaps": ["g"] * 5, "recommendations": [],
            "hypotheses": [{"cause_component": "a", "cause_summary": "s" * 400, "confidence": 1.4,
                            "claims": [{"text": "t" * 300, "evidence_ids": ["E1"] * 9}] * 5}] * 4}
    data, edits = normalise(json.loads(json.dumps(long)))
    from logagent_rca.schemas import FinalReport
    r = FinalReport.model_validate(data)
    assert len(r.hypotheses) == 3 and len(r.hypotheses[0].claims) == 3 and edits > 0
    assert len(r.hypotheses[0].claims[0].text) == 160 and r.hypotheses[0].confidence == 1.0
