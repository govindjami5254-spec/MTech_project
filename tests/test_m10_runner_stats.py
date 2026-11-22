"""M10 tests: runner, scoring, exploratory statistics (scripted LLM; no Ollama)."""
import json
from pathlib import Path

import numpy as np
import pytest

from logagent_rca.analyze import analyze, load_records
from logagent_rca.config import load_config, parse_override
from logagent_rca.llm import LLMResponse, ScriptedLLM, ToolCall
from logagent_rca.metrics import score, score_all
from logagent_rca.runner import RunnerError, planned_runs, run_experiment, verify_split
from logagent_rca.schemas import ArmId, RunRecord
from logagent_rca.stats import holm, paired
from logagent_rca.truth import TruthStore

ROOT = Path(__file__).resolve().parent.parent
STORE = TruthStore(ROOT / "data/synthetic/dev/truth")
CASES = ["dev-c004", "dev-c006", "dev-c010"]          # easy, over_budget, insufficient


def cfg_for(tmp_path, **over):
    base = {"experiment.output_dir": str(tmp_path / "out"), "experiment.repeats": 2}
    base.update(over)
    return load_config(ROOT / "configs/dev.yaml", base)


def oracle_llm():
    """Answers the truth via tools; the final answer cites an evidence line that mentions the cause."""
    def script(messages, tools, schema):
        text = "\n".join(m.get("content") or "" for m in messages)
        if schema:
            import re
            ids = re.findall(r"\[(E\d+)\] \S+ (?:ERROR|FATAL) (\S+) ", text)
            target = ids[0] if ids else None
            if not target:
                return LLMResponse(content=json.dumps({"insufficient_evidence": True, "hypotheses": [],
                                                       "evidence_gaps": [], "recommendations": []}))
            eid, comp = target
            msg = re.search(rf"\[{eid}\] \S+ \S+ \S+ \(\S+\) (.*)", text).group(1)
            return LLMResponse(content=json.dumps({"insufficient_evidence": False, "hypotheses": [{
                "cause_component": comp, "cause_summary": "x", "confidence": 0.5,
                "claims": [{"text": f"{comp} {msg}"[:150], "evidence_ids": [eid]}]}],
                "evidence_gaps": [], "recommendations": []}), prompt_tokens=100, output_tokens=30)
        n = sum(1 for m in messages if m["role"] == "tool")
        if n < 2:
            return LLMResponse(tool_calls=[ToolCall("error_timeline", {})], prompt_tokens=60, output_tokens=8)
        return LLMResponse(content="DONE", prompt_tokens=60, output_tokens=1)
    return ScriptedLLM(script)


def test_parse_override():
    assert parse_override("agent.coverage_gate=false") == ("agent.coverage_gate", False)
    assert parse_override("budget.evidence_token_budget=2000") == ("budget.evidence_token_budget", 2000)
    with pytest.raises(ValueError):
        parse_override("novalue")


def test_plan_is_repeat_major_and_skips_a3_and_repeated_e1():
    cfg = load_config(ROOT / "configs/dev.yaml", {"experiment.repeats": 2})
    plan = list(planned_runs(cfg, ["a", "b"]))
    assert ("a", ArmId.E1F, 0) in plan and not any(arm == ArmId.A3 for _, arm, _ in plan)
    assert not any(arm in (ArmId.E1, ArmId.E1F) and rep == 1 for _, arm, rep in plan)
    first_rep1 = next(i for i, (_, _, r) in enumerate(plan) if r == 1)
    assert all(r == 0 for _, _, r in plan[:first_rep1])


def test_runner_end_to_end_resumable_and_records_valid(tmp_path):
    cfg = cfg_for(tmp_path)
    done = run_experiment(cfg, CASES, llm=oracle_llm(), log=lambda m: None)
    # per case: E1, E1f once; E2b, E3, A2 twice
    assert len(done) == len(CASES) * (2 + 3 * 2)
    out = tmp_path / "out"
    recs = load_records(out)
    assert all(isinstance(r, RunRecord) for r in recs)
    e3 = next(r for r in recs if r.arm == ArmId.E3)
    assert e3.model.name == "scripted" and e3.validation is not None and e3.report_validated is not None
    assert (out / "audit" / f"{e3.run_id}.jsonl").exists() and (out / "transcripts" / f"{e3.run_id}.json").exists()
    assert all(r.metrics.unique_evidence_tokens <= cfg.budget.evidence_token_budget for r in recs)
    a2 = next(r for r in recs if r.arm == ArmId.A2)
    assert a2.metrics.gate_rounds == 0
    assert run_experiment(cfg, CASES, llm=oracle_llm(), log=lambda m: None) == []      # resumable
    assert json.loads((out / "config.json").read_text())["config_hash"] == e3.config_hash


def test_ground_truth_never_reaches_arms(tmp_path):
    cfg = cfg_for(tmp_path, **{"experiment.repeats": 1})
    llm = oracle_llm()
    run_experiment(cfg, CASES, llm=llm, log=lambda m: None)
    blob = json.dumps(llm.calls)
    for cid in CASES:
        t = STORE.load(cid)
        assert t.family_id not in blob and '"root_causes"' not in blob and "key_evidence" not in blob


def test_scoring_and_a3_rows(tmp_path):
    cfg = cfg_for(tmp_path, **{"experiment.repeats": 1})
    run_experiment(cfg, CASES, llm=oracle_llm(), log=lambda m: None)
    recs = load_records(tmp_path / "out")
    rows = score_all(recs, {c: STORE.load(c) for c in CASES})
    arms = {r["arm"] for r in rows}
    assert arms == {"E1", "E1f", "E2b", "E3", "A2", "A3"}
    e1 = {r["case_id"]: r for r in rows if r["arm"] == "E1"}
    assert e1["dev-c010"]["correct"] == 1 and e1["dev-c010"]["expected_abstain"]       # silent case
    floor = [r for r in rows if r["arm"] == "E1f"]
    assert all(r["correct"] == 0 for r in floor)                                        # symptom != cause
    for r in rows:
        assert r["correct"] in (0, 1) and (r["evidence_precision"] is None or 0 <= r["evidence_precision"] <= 1)


def test_failed_run_scores_as_incorrect(tmp_path):
    cfg = cfg_for(tmp_path, **{"experiment.repeats": 1})
    bad = ScriptedLLM(lambda m, t, s: LLMResponse(content="garbage"))
    run_experiment(cfg, ["dev-c004"], arms=[ArmId.E2B], llm=bad, log=lambda m: None)
    rec = load_records(tmp_path / "out")[0]
    row = score(rec, STORE.load("dev-c004"))
    assert rec.status.value == "failed" and row["correct"] == 0


def test_verify_split_detects_tampering(tmp_path):
    import shutil
    src = ROOT / "data/synthetic/dev"
    dst = tmp_path / "dev"
    shutil.copytree(src, dst)
    cfg = load_config(ROOT / "configs/dev.yaml", {"data.cases_dir": str(dst / "cases"),
                                                   "data.truth_dir": str(dst / "truth"),
                                                   "data.sums_file": str(dst / "SHA256SUMS")})
    verify_split(cfg)
    f = next((dst / "cases" / "dev-c001").glob("*.log"))
    f.write_text(f.read_text() + "2026-01-01T00:00:00Z ERROR x tampered\n")
    with pytest.raises(RunnerError, match="frozen data changed"):
        verify_split(cfg)


def test_test_split_requires_clean_tree(tmp_path, monkeypatch):
    import logagent_rca.runner as runner
    monkeypatch.setattr(runner, "git_commit", lambda root: ("a" * 40, True))
    cfg = load_config(ROOT / "configs/test.yaml", {"experiment.output_dir": str(tmp_path / "o")})
    with pytest.raises(RunnerError, match="clean git"):
        run_experiment(cfg, ["test-c001"], llm=oracle_llm(), log=lambda m: None)


# ------------------------------------------------------------------ statistics
def _rows(diffs_by_family, arm_a="E3", arm_b="E2b"):
    rows = []
    for f, vals in diffs_by_family.items():
        for i, (a, b) in enumerate(vals):
            for arm, v in ((arm_a, a), (arm_b, b)):
                rows.append({"arm": arm, "case_id": f"{f}-{i}", "family_id": f, "stratum": "easy", "correct": v})
    return rows


def test_paired_effect_permutation_bootstrap_mcnemar():
    rows = _rows({f"f{k}": [(1, 0), (1, 0), (1, 1)] for k in range(8)})
    res = paired(rows, "correct", "E3", "E2b", n_boot=2000)
    assert res["n_cases"] == 24 and res["n_families"] == 8
    assert res["effect"] == pytest.approx(2 / 3)
    assert res["perm_p"] == pytest.approx(2 / 2 ** 8)            # only all-plus / all-minus as extreme
    assert res["ci95"][0] <= res["effect"] <= res["ci95"][1]
    assert res["mcnemar"]["a_only"] == 16 and res["mcnemar"]["b_only"] == 0


def test_paired_null_effect():
    rows = _rows({f"f{k}": [(1, 0), (0, 1)] for k in range(6)})
    res = paired(rows, "correct", "E3", "E2b", n_boot=1000)
    assert res["effect"] == 0 and res["perm_p"] == 1.0


def test_repeats_are_averaged_within_case():
    rows = [{"arm": a, "case_id": "c1", "family_id": "f", "stratum": "easy", "correct": v}
            for a, v in (("E3", 1), ("E3", 0), ("E3", 1), ("E2b", 0), ("E2b", 0), ("E2b", 0))]
    res = paired(rows, "correct", "E3", "E2b", n_boot=100)
    assert res["n_cases"] == 1 and res["effect"] == pytest.approx(2 / 3)


def test_holm():
    adj = holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adj["a"] == pytest.approx(0.03) and adj["c"] == pytest.approx(0.06) and adj["b"] == pytest.approx(0.06)


def test_analyze_writes_outputs(tmp_path):
    cfg = cfg_for(tmp_path, **{"experiment.repeats": 1})
    run_experiment(cfg, CASES, llm=oracle_llm(), log=lambda m: None)
    res = analyze(cfg, tmp_path / "out", n_boot=200)
    assert res["primary"]["a"] == "E3" and "EXPLORATORY" in res["note"]
    md = (tmp_path / "out" / "analysis" / "analysis.md").read_text()
    assert "PRIMARY correct: E3 − E2b" in md and "no claim of statistical significance" in md
