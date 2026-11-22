"""M7 tests: E3 agent loop with a scripted LLM."""
import json
from pathlib import Path

from logagent_rca.config import load_config
from logagent_rca.context import open_case
from logagent_rca.e2b import run_e2b
from logagent_rca.llm import LLMError, LLMResponse, ScriptedLLM, ToolCall
from logagent_rca.agent import run_e3
from logagent_rca.prompts import FINAL_INSTRUCTION, FINAL_SCHEMA, SYSTEM_PROMPT
from logagent_rca.safety import AuditLog
from logagent_rca.schemas import RunStatus
from logagent_rca.tokens import counter_from_config
from logagent_rca.truth import TruthStore

ROOT = Path(__file__).resolve().parent.parent
CFG = load_config(ROOT / "configs" / "dev.yaml")
COUNTER = counter_from_config(CFG.budget)
STORE = TruthStore(CFG.data.truth_dir)


def case(stratum):
    cid = next(c for c in STORE.case_ids() if STORE.load(c).stratum.value == stratum)
    return open_case(CFG.data.cases_path / cid, CFG), STORE.load(cid)


def final(comp="journal-db", ids=("E2",)):
    return LLMResponse(content=json.dumps({"insufficient_evidence": False, "hypotheses": [{
        "cause_component": comp, "cause_summary": "disk full", "confidence": 0.8,
        "claims": [{"text": f"{comp} wrote no space left", "evidence_ids": list(ids)}]}],
        "evidence_gaps": [], "recommendations": []}), prompt_tokens=100, output_tokens=40)


def scripted(plan):
    state = {"i": 0}

    def script(messages, tools, schema):
        if schema:
            return final()
        if state["i"] < len(plan):
            name, args = plan[state["i"]]
            state["i"] += 1
            return LLMResponse(tool_calls=[ToolCall(name, args)], prompt_tokens=50, output_tokens=10)
        return LLMResponse(content="DONE", prompt_tokens=50, output_tokens=2)
    return ScriptedLLM(script)


def test_e3_runs_tools_then_shared_final_call(tmp_path):
    ctx, truth = case("multi_hop")
    llm = scripted([("error_timeline", {}), ("search_logs", {"component": truth.root_causes[0]})])
    r = run_e3(ctx, CFG, llm, COUNTER, 5, AuditLog(tmp_path / "a.jsonl", "r"))
    assert r.status == RunStatus.OK and r.steps == 3 and len(r.tool_calls) == 2
    assert r.ledger.used <= CFG.budget.evidence_token_budget
    last = llm.calls[-1]
    assert last[0]["content"] == SYSTEM_PROMPT and last[-1]["content"] == FINAL_INSTRUCTION
    assert any(m["role"] == "tool" for m in last)                   # trace visible to the final call
    assert r.llm.calls == 4 and r.llm.prompt_tokens == 3 * 50 + 100
    kinds = [json.loads(l)["kind"] for l in (tmp_path / "a.jsonl").read_text().splitlines()]
    assert kinds[0] == "e3_start" and kinds[-1] == "e3_end" and "tool_call" in kinds


def test_min_tool_calls_is_enforced(tmp_path):
    ctx, _ = case("easy")
    llm = scripted([])                                    # tries to finish immediately
    r = run_e3(ctx, CFG, llm, COUNTER, 1, AuditLog(None, "r"))
    assert r.steps == CFG.agent.max_steps and r.status == RunStatus.OK
    assert sum("Gather evidence" in m.get("content", "") for m in llm.calls[-1]) >= 1


def test_step_budget_stops_endless_tool_use(tmp_path):
    ctx, _ = case("easy")
    llm = scripted([("error_timeline", {})] * 50)
    r = run_e3(ctx, CFG, llm, COUNTER, 1, AuditLog(None, "r"))
    assert r.steps == CFG.agent.max_steps


def test_blocked_calls_abort_and_are_counted(tmp_path):
    ctx, _ = case("easy")
    llm = scripted([("run_shell", {"cmd": "id"})] * 10)
    r = run_e3(ctx, CFG, llm, COUNTER, 1, AuditLog(None, "r"))
    assert r.blocked_calls == CFG.agent.max_blocked_calls and r.notes["aborted"] == "too_many_blocked_calls"


def test_max_three_calls_per_turn(tmp_path):
    ctx, _ = case("easy")
    state = {"done": False}

    def script(messages, tools, schema):
        if schema:
            return final()
        if not state["done"]:
            state["done"] = True
            return LLMResponse(tool_calls=[ToolCall("error_timeline", {})] * 5)
        return LLMResponse(content="DONE")
    r = run_e3(ctx, CFG, ScriptedLLM(script), COUNTER, 1, AuditLog(None, "r"))
    assert len(r.tool_calls) == 3


def test_llm_error_still_attempts_final_and_records(tmp_path):
    ctx, _ = case("easy")

    def script(messages, tools, schema):
        if schema:
            return final()
        raise LLMError("connection reset")
    r = run_e3(ctx, CFG, ScriptedLLM(script), COUNTER, 1, AuditLog(None, "r"))
    assert r.notes["aborted"].startswith("llm_error") and r.status == RunStatus.OK


def test_e2b_and_e3_share_final_instruction_and_schema():
    ctx, _ = case("easy")
    seen = []

    def script(messages, tools, schema):
        if schema:
            seen.append((messages[0]["content"], messages[-1]["content"], schema))
            return final()
        return LLMResponse(content="DONE")
    run_e2b(ctx, CFG, ScriptedLLM(script), COUNTER, 1)
    run_e3(ctx, CFG.model_copy(update={"agent": CFG.agent.model_copy(update={"min_tool_calls": 0})}),
           ScriptedLLM(script), COUNTER, 1, AuditLog(None, "r"))
    assert seen[0] == seen[1] == (SYSTEM_PROMPT, FINAL_INSTRUCTION, FINAL_SCHEMA)
