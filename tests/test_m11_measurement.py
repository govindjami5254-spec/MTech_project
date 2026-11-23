"""M11 tests: corrected memory measurement and persisted truncation counts (no behaviour change)."""
import json
from pathlib import Path

import psutil
import pytest

from logagent_rca.analyze import analyze, load_records
from logagent_rca.config import load_config
from logagent_rca.context import LLMUsage
from logagent_rca.finalize import request_final
from logagent_rca.llm import LLMResponse, ScriptedLLM, ToolCall
from logagent_rca.metrics import score_all
from logagent_rca.resources import ResourceSampler, ollama_tree, sample_memory
from logagent_rca.runner import run_experiment
from logagent_rca.schemas import ArmId
from logagent_rca.truth import TruthStore

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ fake processes
class FakeMem:
    def __init__(self, rss, uss=None, pss=None):
        self.rss, self.uss = rss, uss
        if pss is not None:
            self.pss = pss


class FakeProc:
    def __init__(self, pid, name, rss_mb, uss_mb=None, pss_mb=None, children=(), cpu=1.0, denied=False):
        self.pid, self._name, self._children, self._cpu, self._denied = pid, name, list(children), cpu, denied
        self._mem = FakeMem(rss_mb * 1e6, None if uss_mb is None else uss_mb * 1e6,
                            None if pss_mb is None else pss_mb * 1e6)

    def name(self):
        return self._name

    def exe(self):
        return f"/opt/{self._name}"

    def children(self, recursive=False):
        return self._children

    def memory_info(self):
        if self._denied:
            raise psutil.AccessDenied(self.pid)
        return self._mem

    def memory_full_info(self):
        return self._mem

    def cpu_percent(self, interval=None):
        return 50.0

    def cpu_times(self):
        return type("T", (), {"user": self._cpu, "system": 0.0})()


def test_tree_matches_by_process_name_and_counts_each_pid_once():
    runner = FakeProc(20, "llama-server", 6500, 6490, 6495)
    server = FakeProc(10, "ollama", 35, 34, 34, children=[runner])
    shell = FakeProc(30, "bash", 3)            # e.g. 'bash -c "curl ... ollama ..."' must not match
    procs = [shell, server, runner, server]    # duplicates in the iteration
    tree = ollama_tree(lambda: procs)
    assert [p.pid for p in tree] == [10, 20]


def test_sample_memory_separates_rss_uss_pss():
    a = FakeProc(1, "ollama", 100, 80, 90)
    b = FakeProc(2, "llama-server", 6500, 6400, 6450)
    m = sample_memory([a, b], full=True)
    assert m == {"rss": pytest.approx(6600), "uss": pytest.approx(6480), "pss": pytest.approx(6540)}
    assert sample_memory([a, b], full=False)["uss"] is None          # not sampled this tick


def test_missing_metrics_are_none_and_denied_processes_skipped():
    no_pss = FakeProc(1, "ollama", 100, 80)            # e.g. Windows: no PSS
    denied = FakeProc(2, "llama-server", 999, 999, denied=True)
    m = sample_memory([no_pss, denied], full=True)
    assert m["rss"] == pytest.approx(100) and m["uss"] == pytest.approx(80) and m["pss"] is None


def test_sampler_reports_peaks_and_host_context():
    runner = FakeProc(20, "llama-server", 6500, 6400, 6450, cpu=5.0)
    with ResourceSampler(interval=0.01, tree=lambda: [runner]) as s:
        runner._cpu = 7.5
        import time
        time.sleep(0.05)
    d = s.as_dict()
    assert d["peak_rss_mb"] == pytest.approx(6500) and d["peak_uss_mb"] == pytest.approx(6400)
    assert d["peak_pss_mb"] == pytest.approx(6450) and d["cpu_seconds"] == pytest.approx(2.5)
    assert d["mean_cpu_percent"] > 0
    assert d["host_total_mb"] and d["host_used_peak_mb"] <= d["host_total_mb"]


def test_sampler_without_ollama_records_none():
    with ResourceSampler(interval=0.01, tree=lambda: []) as s:
        pass
    assert s.peak_rss_mb is None and s.peak_uss_mb is None and s.cpu_seconds == 0 and s.mean_cpu_percent is None


def test_real_tree_contains_no_shell_processes():
    for p in ollama_tree():
        assert p.name() not in ("bash", "sh", "zsh", "python", "python3")


# ------------------------------------------------------------------ truncation counts
def _report(n_long_claims=0, long_summary=False, extra_gaps=0):
    claims = [{"text": ("x" * 200) if i < n_long_claims else "db logged no space left", "evidence_ids": ["E1"]}
              for i in range(max(1, n_long_claims))]
    return json.dumps({"insufficient_evidence": False, "hypotheses": [{
        "cause_component": "db", "cause_summary": "s" * 300 if long_summary else "disk full",
        "confidence": 0.5, "claims": claims}], "evidence_gaps": ["g"] * (1 + extra_gaps), "recommendations": []})


@pytest.mark.parametrize("content,expected", [
    (_report(), 0),                                            # no truncation
    (_report(long_summary=True), 1),                           # one field
    (_report(n_long_claims=2, long_summary=True, extra_gaps=2), 4),   # 2 claim texts + summary + gap list
])
def test_request_final_counts_truncations(content, expected):
    usage = LLMUsage()
    report, err = request_final(ScriptedLLM(lambda m, t, s: LLMResponse(content=content)),
                                [{"role": "user", "content": "x"}], 1, usage, 0)
    assert report is not None and usage.normalised_fields == expected


def test_truncation_count_persisted_and_identical_across_arms(tmp_path):
    long = _report(n_long_claims=1, long_summary=True)

    def script(messages, tools, schema):
        if schema:
            return LLMResponse(content=long)
        if sum(1 for m in messages if m["role"] == "tool") < 2:
            return LLMResponse(tool_calls=[ToolCall("error_timeline", {})])
        return LLMResponse(content="DONE")

    cfg = load_config(ROOT / "configs/dev.yaml", {"experiment.output_dir": str(tmp_path / "o"),
                                                  "experiment.repeats": 1})
    run_experiment(cfg, ["dev-c004"], arms=[ArmId.E1, ArmId.E2B, ArmId.E3, ArmId.A2],
                   llm=ScriptedLLM(script), log=lambda m: None)
    recs = {r.arm: r for r in load_records(tmp_path / "o")}
    assert recs[ArmId.E2B].metrics.normalised_fields == recs[ArmId.E3].metrics.normalised_fields \
        == recs[ArmId.A2].metrics.normalised_fields == 2
    assert recs[ArmId.E1].metrics.normalised_fields == 0            # no LLM output to normalise
    rows = score_all(list(recs.values()), {"dev-c004": TruthStore(cfg.data.truth_dir).load("dev-c004")})
    assert {r["arm"]: r["normalised_fields"] for r in rows}["A3"] == 2
    res = analyze(cfg, tmp_path / "o", n_boot=100)
    assert res["summary"]["E2b"]["normalised_fields_total"] == 2 and res["summary"]["E2b"]["runs_with_truncation"] == 1


def test_old_records_without_new_fields_still_load():
    recs = load_records(ROOT / "results" / "dev-pilot") if (ROOT / "results/dev-pilot/runs").exists() else []
    if not recs:
        pytest.skip("pilot records not present")
    assert all(r.metrics.normalised_fields == 0 and r.metrics.peak_uss_mb is None for r in recs)
