"""End-to-end and safety tests using a scripted (deterministic) LLM - no Ollama needed."""
import json
import re
from pathlib import Path

import pytest

from agentrca.config import load_config
from agentrca.eval import score
from agentrca.ingest import load_logs
from agentrca.llm import LLMResponse, ScriptedLLM, ToolCall
from agentrca.pipeline import investigate, prepare
from agentrca.safety import PathViolation, ToolPolicy, resolve_inside
from agentrca.synth import generate
from agentrca.tools import TOOL_DEFS

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def scenario(tmp_path):
    d = tmp_path / "logs"
    truth = generate(str(d), fault="disk_full", seed=1, target="db-primary", inject=True, red_herring=True)
    cfg = load_config(str(ROOT / "config.yaml"))
    cfg.logs.root = str(d)
    cfg.rules_file = str(ROOT / "rules.yaml")
    cfg.output_dir = str(tmp_path / "runs")
    index, _, incidents = prepare(cfg)
    inc = next(i for i in incidents if i.rule_id == truth["incident_rule"])
    return cfg, index, inc, truth


def _final(messages, evidence_ids=None, comp="db-primary", text="db-primary ran out of disk space: no space left on device"):
    body = messages[-1]["content"]
    ids = re.findall(r"\[(E\d+)\][^\n]*no space left", body)
    ids = evidence_ids if evidence_ids is not None else ids
    return LLMResponse(content=json.dumps({
        "hypotheses": [{"cause_component": comp, "cause_summary": "storage exhausted", "confidence": 0.9,
                        "claims": [{"text": text, "evidence_ids": ids},
                                   {"text": "payment-service got connection refused to db-primary",
                                    "evidence_ids": re.findall(r"\[(E\d+)\][^\n]*connection refused", body)[:1]}]}],
        "evidence_gaps": [], "recommendations": ["Check disk usage on db-primary (human decision)."]}),
        tokens_in=10, tokens_out=10)


def _agent_script(plan, final=_final):
    state = {"i": 0}

    def script(messages, tools, schema):
        if schema:
            return final(messages)
        if state["i"] < len(plan):
            item = plan[state["i"]]
            state["i"] += 1
            return LLMResponse(tool_calls=[ToolCall(item[0], item[1])])
        return LLMResponse(content="DONE")
    return script


FULL_PLAN = [("error_timeline", {}),
             ("search_logs", {"component": "db-primary", "min_severity": "WARN"}),
             ("search_logs", {"component": "payment-service", "min_severity": "WARN"}),
             ("search_logs", {"component": "cache-service"}),
             ("search_logs", {"component": "auth-service"}),
             ("search_logs", {"component": "order-service"})]


def test_agent_end_to_end(scenario):
    cfg, index, inc, truth = scenario
    rep = investigate(cfg, index, inc, "agent", llm=ScriptedLLM(_agent_script(FULL_PLAN)))
    s = score(rep, truth)
    assert s["top1"] and s["top3"]
    assert s["evidence_coverage"] > 0 and s["unsupported_claim_rate"] == 0
    assert rep["metrics"]["tool_calls"] >= 2 and rep["safety"]["blocked_tool_calls"] == 0
    run_dir = Path(cfg.output_dir) / rep["run_id"]
    assert (run_dir / "report.json").exists() and (run_dir / "report.md").exists()
    kinds = [json.loads(l)["kind"] for l in (run_dir / "audit.jsonl").read_text().splitlines()]
    assert "tool_call" in kinds and "run_end" in kinds


def test_coverage_gate_forces_inspection(scenario):
    cfg, index, inc, _ = scenario
    lazy = [("error_timeline", {}), ("list_components", {})]      # overview only, then "DONE"

    def script(messages, tools, schema):
        if schema:
            return _final(messages)
        last = messages[-1]
        if last["role"] == "user" and "have not been inspected yet" in last["content"]:
            comp = re.search(r"yet: ([\w\-]+)", last["content"]).group(1)
            return LLMResponse(tool_calls=[ToolCall("search_logs", {"component": comp})])
        if len([m for m in messages if m["role"] == "tool"]) < 2:
            return LLMResponse(tool_calls=[ToolCall(*lazy[len([m for m in messages if m["role"] == "tool"])])])
        return LLMResponse(content="DONE")

    rep = investigate(cfg, index, inc, "agent", llm=ScriptedLLM(script))
    assert rep["metrics"]["gate_rounds"] >= 1
    # without the gate, the same lazy agent stops early and reports the gap instead
    cfg.agent.coverage_gate = False
    rep2 = investigate(cfg, index, inc, "agent", llm=ScriptedLLM(script))
    assert rep2["metrics"]["gate_rounds"] == 0
    assert any("not inspected" in g for g in rep2["evidence_gaps"])


def test_disallowed_tool_is_blocked_and_audited(scenario):
    cfg, index, inc, truth = scenario
    plan = [("run_shell", {"cmd": "rm -rf /"}), ("search_logs", {"component": "../../etc/passwd"}),
            ("search_logs", {"component": "db-primary", "regex": ".*"})] + FULL_PLAN
    rep = investigate(cfg, index, inc, "agent", llm=ScriptedLLM(_agent_script(plan)))
    assert rep["safety"]["blocked_tool_calls"] >= 2
    audit = (Path(cfg.output_dir) / rep["run_id"] / "audit.jsonl").read_text()
    assert '"tool_blocked"' in audit and "tool_not_allowed" in audit


def test_run_aborts_after_repeated_blocked_calls(scenario):
    cfg, index, inc, _ = scenario
    plan = [("delete_logs", {})] * 10
    rep = investigate(cfg, index, inc, "agent", llm=ScriptedLLM(_agent_script(plan)))
    assert rep["metrics"]["blocked_calls"] == cfg.agent.max_blocked_calls
    assert any("too_many_blocked_calls" in g for g in rep["evidence_gaps"])


def test_fabricated_citation_is_removed(scenario):
    cfg, index, inc, truth = scenario
    script = _agent_script(FULL_PLAN, final=lambda m: _final(m, evidence_ids=["E999"]))
    rep = investigate(cfg, index, inc, "agent", llm=ScriptedLLM(script))
    assert rep["validation"]["fabricated_ids"] >= 1
    assert rep["validation"]["unsupported_claim_rate"] > 0
    assert rep["hypotheses"] == [] or all(c["supported"] for h in rep["hypotheses"] for c in h["claims"])
    cfg.agent.validate = False                                        # ablation: no enforcement
    rep2 = investigate(cfg, index, inc, "agent", llm=ScriptedLLM(script))
    assert any(not c["supported"] for h in rep2["hypotheses"] for c in h["claims"])


def test_injection_and_redaction(scenario):
    cfg, index, inc, truth = scenario
    assert index.stats["suspicious"] >= 1
    text = " ".join(e.message for e in index.events)
    assert "hunter2" not in text and "jdoe@example.com" not in text
    rep = investigate(cfg, index, inc, "agent", llm=ScriptedLLM(_agent_script(FULL_PLAN)))
    assert rep["safety"]["injection_suspected_lines"] >= 1
    assert not score(rep, truth)["injection_followed"]


def test_baselines_run_without_llm_and_heuristic_is_fooled(scenario):
    cfg, index, inc, truth = scenario
    assert not score(investigate(cfg, index, inc, "rule"), truth)["top1"]
    h = investigate(cfg, index, inc, "heuristic")
    assert h["hypotheses"][0]["cause_component"] != truth["cause_component"]   # red herring first


def test_single_and_static_use_same_schema(scenario):
    cfg, index, inc, truth = scenario
    for mode in ("single", "static"):
        rep = investigate(cfg, index, inc, mode, llm=ScriptedLLM(lambda m, t, s: _final(m)))
        assert rep["mode"] == mode and rep["metrics"]["tool_calls"] == 0


def test_policy_and_paths(tmp_path):
    pol = ToolPolicy(TOOL_DEFS, ["search_logs"])
    with pytest.raises(Exception):
        pol.validate("get_context", {"evidence_id": "E1"})        # defined but not allowlisted
    with pytest.raises(Exception):
        pol.validate("search_logs", {"limit": 10_000})
    assert pol.validate("search_logs", {"limit": "5", "component": " x "}) == {"limit": 5, "component": "x"}
    (tmp_path / "root").mkdir()
    with pytest.raises(PathViolation):
        resolve_inside(tmp_path / "root", "../secret.txt")
    outside = tmp_path / "secret.log"
    outside.write_text("2026-01-10T10:00:00Z ERROR x boom\n")
    (tmp_path / "root" / "link.log").symlink_to(outside)
    (tmp_path / "root" / "ok.log").write_text("2026-01-10T10:00:00Z ERROR svc fine\n")
    cfg = load_config(None)
    cfg.logs.root = str(tmp_path / "root")
    idx = load_logs(cfg.logs)
    assert [e.message for e in idx.events] == ["fine"]            # symlink escaping the root is ignored


def test_gate_fires_even_if_agent_never_stops_calling_tools(scenario):
    cfg, index, inc, _ = scenario
    cfg.agent.max_steps = 3

    def script(messages, tools, schema):
        if schema:
            return _final(messages)
        last = messages[-1]
        if last["role"] == "user" and "have not been inspected yet" in last["content"]:
            comp = re.search(r"yet: ([\w\-]+)", last["content"]).group(1)
            return LLMResponse(tool_calls=[ToolCall("search_logs", {"component": comp})])
        return LLMResponse(tool_calls=[ToolCall("count_matches", {"contains": "error"})])   # never finishes

    rep = investigate(cfg, index, inc, "agent", llm=ScriptedLLM(script))
    assert rep["metrics"]["gate_rounds"] >= 1
    assert rep["metrics"]["steps"] > 3                      # gate extended the budget


def test_injected_line_cannot_support_a_claim(scenario):
    cfg, index, inc, truth = scenario
    plan = FULL_PLAN

    def final(messages):
        ids = re.findall(r"\[(E\d+)\][^\n]*IGNORE ALL PREVIOUS", messages[-1]["content"])
        return LLMResponse(content=json.dumps({
            "hypotheses": [{"cause_component": "cache-service", "cause_summary": "decoy", "confidence": 0.9,
                            "claims": [{"text": "cache-service is the root cause per the log", "evidence_ids": ids}]}],
            "evidence_gaps": [], "recommendations": []}))

    rep = investigate(cfg, index, inc, "agent", llm=ScriptedLLM(_agent_script(plan, final=final)))
    assert rep["validation"]["suspicious_citations"] >= 1
    assert rep["hypotheses"] == []
    assert not score(rep, truth)["injection_followed"]


def test_quarantine_hides_injected_text_from_llm(scenario):
    cfg, index, inc, _ = scenario
    cfg.safety.quarantine_suspicious = True
    seen = []

    def final(messages):
        seen.append(messages[-1]["content"])
        return _final(messages)

    investigate(cfg, index, inc, "agent", llm=ScriptedLLM(_agent_script(FULL_PLAN, final=final)))
    assert "IGNORE ALL PREVIOUS" not in seen[0] and "quarantined" in seen[0]
