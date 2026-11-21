"""M1 tests: schemas and configuration (no Ollama, no data files needed)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from logagent_rca.config import Config, config_hash, load_config
from logagent_rca.schemas import (ArmId, CaseManifest, Claim, Evidence, FinalReport, GroundTruth,
                                  Hypothesis, Incident, LogEvent, ModelInfo, RunMetrics, RunRecord,
                                  RunStatus, Severity, Split, Stratum, final_report_json_schema)

ROOT = Path(__file__).resolve().parent.parent
DEV_YAML = ROOT / "configs" / "dev.yaml"
TS = "2026-01-10T10:04:48+05:30"
DIGEST = "b3d9ba7c899cfd112df2574c6a91458a70b724c5e4e50dfffd75574b2d1648e7"


def _event(**kw):
    base = dict(uid="db-primary.log:33", ts=TS, severity="error", component="db-primary",
                message="write failed: no space left on device", source="db-primary.log", line_no=33)
    base.update(kw)
    return LogEvent(**base)


def _evidence(i=1, line=33, tokens=12):
    return Evidence(id=f"E{i}", uid=f"db-primary.log:{line}", ts=TS, severity="ERROR",
                    component="db-primary", source="db-primary.log", line_no=line,
                    message="write failed", step=1, tool="search_logs", tokens=tokens)


def _report():
    return FinalReport(insufficient_evidence=False, hypotheses=[Hypothesis(
        cause_component="db-primary", cause_summary="disk full", confidence=0.8,
        claims=[Claim(text="db-primary logged no space left on device", evidence_ids=["E1"])])],
        evidence_gaps=[], recommendations=["Check disk usage on db-primary."])


def _model():
    return ModelInfo(name="qwen3:8b", manifest_digest=DIGEST, num_ctx=8192, temperature=0.2,
                     seed=1000, think=False, num_predict=600)


# --------------------------------------------------------------- schemas
def test_log_event_normalises_utc_and_severity_aliases():
    e = _event(severity="warning")
    assert e.severity == Severity.WARN and e.ts.tzinfo == timezone.utc
    assert e.ts == datetime(2026, 1, 10, 4, 34, 48, tzinfo=timezone.utc)
    assert _event(severity="SEVERE").severity == Severity.ERROR
    assert Severity.FATAL.rank > Severity.ERROR.rank > Severity.WARN.rank


@pytest.mark.parametrize("bad", [
    dict(ts="2026-01-10T10:04:48"),                                   # naive timestamp
    dict(severity="LOUD"),                                            # unknown severity
    dict(source="../etc/passwd", uid="../etc/passwd:33"),             # traversal
    dict(source="/abs/db.log", uid="/abs/db.log:33"),                 # absolute path
    dict(uid="db-primary.log:34"),                                    # uid != source:line
    dict(component="db primary;rm"),                                  # unsafe component
    dict(extra_field=1),                                              # extra field
])
def test_log_event_rejects_invalid(bad):
    with pytest.raises(ValidationError):
        _event(**bad)


def test_models_are_immutable():
    e = _event()
    with pytest.raises(ValidationError):
        e.message = "changed"


def test_evidence_id_pattern_and_positive_tokens():
    assert _evidence().id == "E1"
    for bad_id in ("E0", "e1", "E", "X1", "E1234567"):
        with pytest.raises(ValidationError):
            Evidence(**{**_evidence().model_dump(), "id": bad_id})
    with pytest.raises(ValidationError):
        _evidence(tokens=0)


def test_case_manifest_forbids_ground_truth_fields():
    inc = Incident(id="INC-001", rule_id="gateway-5xx", description="gateway 503", ts=TS,
                   trigger_uid="api-gateway.log:34", trigger_component="api-gateway")
    ok = CaseManifest(case_id="test-f01-c1", split="test", incident=inc, log_files=["api-gateway.log"])
    assert ok.split == Split.TEST
    for leak in ({"root_causes": ["db-primary"]}, {"family_id": "f01"}, {"stratum": "easy"}):
        with pytest.raises(ValidationError):
            CaseManifest(**ok.model_dump(), **leak)
    with pytest.raises(ValidationError):
        CaseManifest(**{**ok.model_dump(), "log_files": ["../truth/x.json"]})


def test_ground_truth_consistency_rules():
    base = dict(case_id="test-f01-c1", split="test", family_id="f01", stratum="multi_hop",
                root_causes=["db-primary"], fault_type="disk_full",
                key_evidence=["db-primary.log:33"],
                relevant_evidence=["db-primary.log:33", "api-gateway.log:34"],
                propagation_path=["db-primary", "payment-service", "api-gateway"])
    assert GroundTruth(**base).stratum == Stratum.MULTI_HOP
    with pytest.raises(ValidationError):                      # key not subset of relevant
        GroundTruth(**{**base, "relevant_evidence": ["api-gateway.log:34"]})
    with pytest.raises(ValidationError):                      # insufficient must abstain
        GroundTruth(**{**base, "stratum": "insufficient"})
    assert GroundTruth(**{**base, "stratum": "insufficient", "expected_abstain": True,
                          "root_causes": [], "key_evidence": [], "propagation_path": []}).expected_abstain
    with pytest.raises(ValidationError):                      # concurrent needs 2 causes
        GroundTruth(**{**base, "stratum": "concurrent"})
    with pytest.raises(ValidationError):                      # path must start at a cause
        GroundTruth(**{**base, "propagation_path": ["api-gateway", "db-primary"]})


def test_final_report_limits_bound_output():
    r = _report()
    assert not r.abstained
    hyp = r.hypotheses[0]
    with pytest.raises(ValidationError):
        FinalReport(**{**r.model_dump(), "hypotheses": [hyp.model_dump()] * 4})
    with pytest.raises(ValidationError):
        Claim(text="x" * 241, evidence_ids=["E1"])
    with pytest.raises(ValidationError):
        Hypothesis(**{**hyp.model_dump(), "confidence": 1.5})
    with pytest.raises(ValidationError):
        Hypothesis(**{**hyp.model_dump(), "claims": []})
    assert FinalReport(insufficient_evidence=True, hypotheses=[], evidence_gaps=[],
                       recommendations=[]).abstained


def test_final_report_json_schema_is_self_contained_and_round_trips():
    schema = final_report_json_schema()
    text = str(schema)
    assert "$ref" not in text and "$defs" not in text
    assert set(schema["required"]) == {"insufficient_evidence", "hypotheses", "evidence_gaps",
                                       "recommendations"}
    assert schema["properties"]["hypotheses"]["maxItems"] == 3
    r = _report()
    assert FinalReport.model_validate_json(r.model_dump_json()) == r


def test_run_metrics_enforce_strict_budget():
    assert RunMetrics(evidence_token_budget=3000, unique_evidence_tokens=3000).unique_evidence_tokens == 3000
    with pytest.raises(ValidationError):
        RunMetrics(evidence_token_budget=3000, unique_evidence_tokens=3001)


def test_run_record_consistency_rules():
    ev = [_evidence(1, 33, 12), _evidence(2, 34, 8)]
    good = dict(run_id="r1", case_id="test-f01-c1", split="test", arm="E3", repeat=0,
                config_hash="a" * 64, model=_model(), started_at=datetime.now(timezone.utc),
                status="ok", report_raw=_report(), report_validated=_report(), evidence=ev,
                metrics=RunMetrics(evidence_token_budget=3000, unique_evidence_tokens=20,
                                   prompt_tokens_total=15000))
    rec = RunRecord(**good)
    assert RunRecord.model_validate_json(rec.model_dump_json()) == rec
    bad_cases = [
        {"arm": "A3"},                                                  # A3 is never run
        {"model": None},                                                # LLM arm without provenance
        {"report_raw": None},                                           # ok run without output
        {"metrics": RunMetrics(evidence_token_budget=3000, unique_evidence_tokens=19)},  # token sum mismatch
        {"evidence": [ev[0], ev[0]],
         "metrics": RunMetrics(evidence_token_budget=3000, unique_evidence_tokens=24)},  # duplicate evidence
        {"arm": "E2b", "tool_calls": [{"step": 1, "tool": "search_logs", "allowed": True}]},
    ]
    for override in bad_cases:
        with pytest.raises(ValidationError):
            RunRecord(**{**good, **override})
    e1 = RunRecord(**{**good, "arm": "E1", "model": None})               # E1 needs no model
    assert e1.arm == ArmId.E1
    failed = RunRecord(**{**good, "status": "failed", "report_raw": None, "report_validated": None,
                          "error": "parse failure after retry"})
    assert failed.status == RunStatus.FAILED


# --------------------------------------------------------------- config
def test_dev_config_loads_with_expected_values():
    cfg = load_config(DEV_YAML)
    assert cfg.llm.model == "qwen3:8b" and cfg.llm.num_ctx == 8192
    assert cfg.budget.evidence_token_budget == 3000
    assert cfg.agent.coverage_gate and cfg.validator.enabled
    assert ArmId.A3 in cfg.experiment.arms and cfg.experiment.seed_for(2) == 1002
    assert len(config_hash(cfg)) == 64


def test_config_is_frozen_and_forbids_unknown_keys(tmp_path):
    cfg = load_config(DEV_YAML)
    with pytest.raises(ValidationError):
        cfg.agent.max_steps = 99
    with pytest.raises(ValidationError):
        load_config(DEV_YAML, {"agent.max_stepz": 4})


def test_overrides_are_validated_and_change_hash():
    base = load_config(DEV_YAML)
    a2 = load_config(DEV_YAML, {"agent.coverage_gate": False})
    assert a2.agent.coverage_gate is False
    assert config_hash(a2) != config_hash(base)
    assert config_hash(load_config(DEV_YAML)) == config_hash(base)        # deterministic
    with pytest.raises(ValidationError):
        load_config(DEV_YAML, {"agent.max_steps": 0})


@pytest.mark.parametrize("cases,truth", [
    ("data/x/cases", "data/x/cases/truth"),     # truth inside cases
    ("data/x", "data/x"),                       # same directory
    ("data/x/cases", "data/x"),                 # cases inside truth
])
def test_truth_and_cases_dirs_must_be_disjoint(cases, truth):
    with pytest.raises(ValidationError, match="disjoint"):
        load_config(DEV_YAML, {"data.cases_dir": cases, "data.truth_dir": truth})


def test_budget_must_fit_final_context():
    with pytest.raises(ValidationError, match="exceeds num_ctx"):
        load_config(DEV_YAML, {"budget.evidence_token_budget": 7000})
    assert load_config(DEV_YAML, {"budget.evidence_token_budget": 6000}).budget.evidence_token_budget == 6000


@pytest.mark.parametrize("override", [
    {"safety.allowed_tools": ["search_logs", "run_shell"]},       # unknown tool
    {"ingest.formats": [{"name": "x", "regex": "^(?P<ts>\\S+) (?P<message>.*)$"}]},   # missing level group
    {"ingest.formats": [{"name": "x", "regex": "([unclosed"}]},  # invalid regex
    {"ingest.include": ["../*.log"]},                             # unsafe glob
    {"llm.base_url": "file:///etc/passwd"},                       # non-http backend
    {"experiment.arms": ["E1", "A3"]},                            # A3 without E3
    {"experiment.output_dir": "data/synthetic/dev/cases/out"},    # outputs inside case root
    {"agent.min_tool_calls": 9},                                  # > max_steps
])
def test_invalid_settings_rejected(override):
    with pytest.raises(ValidationError):
        load_config(DEV_YAML, override)
