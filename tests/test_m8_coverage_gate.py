"""M8 tests: coverage gate behaviour (E3) versus A2 (gate disabled)."""
import json
import re
from pathlib import Path

from logagent_rca.agent import run_e3
from logagent_rca.config import load_config
from logagent_rca.context import open_case
from logagent_rca.coverage import make_gate, pending_components
from logagent_rca.evidence import EvidenceLedger
from logagent_rca.llm import LLMResponse, ScriptedLLM, ToolCall
from logagent_rca.safety import AuditLog
from logagent_rca.tokens import counter_from_config
from logagent_rca.tools import ToolRegistry
from logagent_rca.truth import TruthStore

ROOT = Path(__file__).resolve().parent.parent
CFG = load_config(ROOT / "configs" / "dev.yaml")
COUNTER = counter_from_config(CFG.budget)
STORE = TruthStore(CFG.data.truth_dir)
GATE = make_gate(CFG.agent.lookback_s)


def case(stratum):
    cid = next(c for c in STORE.case_ids() if STORE.load(c).stratum.value == stratum)
    return open_case(CFG.data.cases_path / cid, CFG), STORE.load(cid)


FINAL = json.dumps({"insufficient_evidence": True, "hypotheses": [], "evidence_gaps": [], "recommendations": []})


def lazy_but_obedient():
    """Calls error_timeline twice, then wants to finish; obeys gate messages by inspecting the first name."""
    def script(messages, tools, schema):
        if schema:
            return LLMResponse(content=FINAL)
        last = messages[-1]
        if last["role"] == "user" and "have not examined them" in last["content"]:
            comp = re.search(r"examined them: ([\w.-]+)", last["content"]).group(1)
            return LLMResponse(tool_calls=[ToolCall("search_logs", {"component": comp, "min_severity": "WARN"})])
        n_tools = sum(1 for m in messages if m["role"] == "tool")
        if n_tools < 2:
            return LLMResponse(tool_calls=[ToolCall("error_timeline", {})])
        return LLMResponse(content="DONE")
    return ScriptedLLM(script)


def test_pending_lists_uninspected_problem_components_in_time_order():
    ctx, truth = case("distractor")
    reg = ToolRegistry(ctx, EvidenceLedger(3000, COUNTER), CFG.safety, AuditLog(None, "r"), CFG.agent.lookback_s)
    pend = [c for c, _ in pending_components(reg, CFG.agent.lookback_s)]
    assert truth.root_causes[0] in pend and ctx.trigger.component not in pend
    reg.inspected.add(truth.root_causes[0])
    assert truth.root_causes[0] not in [c for c, _ in pending_components(reg, CFG.agent.lookback_s)]


def test_gate_forces_inspection_and_a2_does_not(tmp_path):
    ctx, truth = case("distractor")
    e3 = run_e3(ctx, CFG, lazy_but_obedient(), COUNTER, 1, AuditLog(tmp_path / "e3.jsonl", "e3"), gate=GATE)
    a2 = run_e3(ctx, CFG, lazy_but_obedient(), COUNTER, 1, AuditLog(tmp_path / "a2.jsonl", "a2"), gate=None)
    assert e3.gate_rounds >= 1 and a2.gate_rounds == 0
    assert len(e3.notes["inspected"]) > len(a2.notes["inspected"])
    assert e3.ledger.used >= a2.ledger.used
    kinds = [json.loads(l)["kind"] for l in (tmp_path / "e3.jsonl").read_text().splitlines()]
    assert "coverage_gate" in kinds and "coverage_gate_pending" in kinds


def test_gate_rounds_are_bounded(tmp_path):
    ctx, _ = case("over_budget")
    def stubborn(messages, tools, schema):          # ignores the gate, keeps saying DONE
        if schema:
            return LLMResponse(content=FINAL)
        if sum(1 for m in messages if m["role"] == "tool") < 2:
            return LLMResponse(tool_calls=[ToolCall("error_timeline", {})])
        return LLMResponse(content="DONE")
    r = run_e3(ctx, CFG, ScriptedLLM(stubborn), COUNTER, 1, AuditLog(None, "r"), gate=GATE)
    assert r.gate_rounds == CFG.agent.max_gate_rounds


def test_gate_extends_step_budget_when_steps_run_out(tmp_path):
    ctx, _ = case("distractor")
    def busy(messages, tools, schema):              # never finishes on its own
        if schema:
            return LLMResponse(content=FINAL)
        return LLMResponse(tool_calls=[ToolCall("error_timeline", {})])
    r = run_e3(ctx, CFG, ScriptedLLM(busy), COUNTER, 1, AuditLog(None, "r"), gate=GATE)
    assert r.steps > CFG.agent.max_steps and r.gate_rounds >= 1


def test_gate_is_silent_when_budget_exhausted(tmp_path):
    ctx, _ = case("distractor")
    reg = ToolRegistry(ctx, EvidenceLedger(100, COUNTER), CFG.safety, AuditLog(None, "r"), CFG.agent.lookback_s)
    reg.ledger.offer([ctx.trigger], 0, "incident")
    reg.execute("error_timeline", {}, 1)
    assert reg.ledger.remaining < 60 and GATE(reg, 2) is None
    assert reg.audit.count("coverage_gate_skipped") == 1
