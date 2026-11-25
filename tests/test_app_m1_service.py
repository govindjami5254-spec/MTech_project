"""Application M1: shared services, store, renderer, CLI (scripted LLM; no Ollama)."""
import json
from pathlib import Path

import pytest

from app_helpers import DEV_CASE, ROOT, dev_inputs, scripted_llm
from logagent_rca.__main__ import main
from logagent_rca.config import load_config
from logagent_rca.report_render import CONFIDENCE_NOTE, build_view, to_markdown
from logagent_rca.runner import run_one
from logagent_rca.schemas import ArmId
from logagent_rca.service import AnalysisRefused, AppService, ValidationProblem, sanitize_filename
from logagent_rca.store import InvestigationStore


@pytest.fixture()
def svc(tmp_path):
    return AppService(workspace=tmp_path / "ws", llm_factory=lambda cfg: scripted_llm(), experiment_guard=lambda: False)


def test_app_config_uses_identical_model_and_research_settings():
    app, test = load_config(ROOT / "configs/app.yaml"), load_config(ROOT / "configs/test.yaml")
    for section in ("llm", "budget", "agent", "validator", "safety", "ingest"):
        assert getattr(app, section) == getattr(test, section), section


def test_create_and_analyze_e2b_and_e3(svc):
    inv = svc.create_investigation(**dev_inputs())
    assert inv.id.startswith("inv-") and inv.status == "created"
    assert (svc.store.case_dir(inv.id) / "incident.json").is_file()
    for mode in ("E2b", "E3"):
        rec = svc.analyze(inv.id, mode)
        assert rec.status.value == "ok" and rec.arm.value == mode
        assert rec.metrics.unique_evidence_tokens <= svc.base_cfg.budget.evidence_token_budget
        assert rec.validation.fabricated_ids == 1                     # the scripted E99 citation
    inv = svc.store.load(inv.id)
    assert [a.status for a in inv.analyses] == ["ok", "ok"]
    assert svc.record(inv.id).arm == ArmId.E3                         # latest completed
    kinds = [e["kind"] for e in svc.store.events(inv.id)]
    assert kinds[:2] == ["input_validated", "logs_ingested"] and "report_validated" in kinds


def test_service_result_equals_direct_engine_on_same_bundle(svc, tmp_path):
    """The service adds nothing to the engine: same bundle + same config -> same validated report and evidence."""
    inv = svc.create_investigation(**dev_inputs())
    via_service = svc.analyze(inv.id, "E3")
    cfg = svc.config_for(inv.id)
    direct = run_one(cfg, inv.id, ArmId.E3, 0, tmp_path / "direct", scripted_llm(), svc.counter, {}, None)
    assert direct.report_validated == via_service.report_validated
    assert direct.report_raw == via_service.report_raw
    assert [e.model_dump() for e in direct.evidence] == [e.model_dump() for e in via_service.evidence]
    assert direct.config_hash == via_service.config_hash


def test_reanalysis_creates_new_repeat_and_never_overwrites(svc):
    inv = svc.create_investigation(**dev_inputs())
    r0 = svc.analyze(inv.id, "E2b")
    r1 = svc.analyze(inv.id, "E2b")
    assert (r0.run_id, r1.run_id) == (f"{inv.id}__E2b__r0", f"{inv.id}__E2b__r1")
    assert r1.model.seed == r0.model.seed + 1


def test_concurrent_request_refused(svc):
    inv = svc.create_investigation(**dev_inputs())
    svc.request_analysis(inv.id, "E3")
    with pytest.raises(AnalysisRefused):
        svc.request_analysis(inv.id, "E2b")


def test_analysis_refused_while_experiment_runs(tmp_path):
    s = AppService(workspace=tmp_path / "ws", llm_factory=lambda c: scripted_llm(), experiment_guard=lambda: True)
    inv = s.create_investigation(**dev_inputs())
    assert s.analyze(inv.id, "E3") is None
    a = s.store.load(inv.id).analyses[-1]
    assert a.status == "error" and "experiment is running" in a.error


def test_ollama_failure_is_recorded_not_raised(tmp_path):
    from logagent_rca.llm import LLMError

    class Down:
        def model_info(self, seed):
            raise LLMError("Ollama request /api/tags failed: connection refused")
    s = AppService(workspace=tmp_path / "ws", llm_factory=lambda c: Down(), experiment_guard=lambda: False)
    inv = s.create_investigation(**dev_inputs())
    assert s.analyze(inv.id, "E2b") is None
    a = s.store.load(inv.id).analyses[-1]
    assert a.status == "error" and "connection refused" in a.error


@pytest.mark.parametrize("field,value,key", [
    ("incident_id", "INCIDENT-1", "incident_id"),
    ("timestamp", "2026-01-10T10:05:00", "timestamp"),
    ("timestamp", "yesterday Z", "timestamp"),
    ("trigger_line", 0, "trigger_line"),
    ("trigger_line", 99999, "trigger_line"),
    ("trigger_component", "someone-else", "trigger_component"),
    ("trigger_component", "bad name;", "trigger_component"),
    ("rule_id", "Bad Rule", "rule_id"),
    ("trigger_file", "missing.log", "trigger_file"),
    ("description", "", "description"),
])
def test_invalid_incident_fields(svc, field, value, key):
    inp = dev_inputs()
    inp[field] = value
    with pytest.raises(ValidationProblem) as e:
        svc.create_investigation(**inp)
    assert key in e.value.errors
    assert not [p for p in svc.store.cases.iterdir()]                 # nothing left behind


def test_trigger_outside_window_rejected(svc):
    inp = dev_inputs()
    inp["timestamp"] = "2030-01-01T00:00:00Z"
    with pytest.raises(ValidationProblem) as e:
        svc.create_investigation(**inp)
    assert "outside the analysis window" in e.value.errors["timestamp"]


def test_report_rendering_resolves_evidence_and_removed_claims(svc):
    inv = svc.create_investigation(**dev_inputs())
    rec = svc.analyze(inv.id, "E3")
    v = build_view(rec, svc.manifest(inv.id))
    ev_ids = {e["id"] for e in v["evidence"]}
    for h in v["hypotheses"]:
        for c in h["claims"]:
            for e in c["evidence"]:
                assert e["id"] in ev_ids and e["source"].endswith(".log") and e["line_no"] >= 1
    assert any(r["unknown_ids"] == ["E99"] for r in v["removed_claims"])
    md = to_markdown(rec, svc.manifest(inv.id))
    assert "Ranked root-cause hypotheses" in md and CONFIDENCE_NOTE in md and "Claims removed by the validator" in md


def test_source_lines_trace_evidence_to_original_file(svc):
    inv = svc.create_investigation(**dev_inputs())
    rec = svc.analyze(inv.id, "E2b")
    e = rec.evidence[0]
    lines = svc.source_lines(inv.id, e.source, e.line_no)
    target = next(l for l in lines if l["target"])
    raw = (svc.store.case_dir(inv.id) / e.source).read_text().splitlines()[e.line_no - 1]
    assert target["text"] == raw and target["line_no"] == e.line_no
    with pytest.raises(KeyError):
        svc.source_lines(inv.id, "../../etc/passwd", 1)


def test_list_filters_and_persistence_across_instances(svc, tmp_path):
    inv = svc.create_investigation(**dev_inputs())
    svc.analyze(inv.id, "E2b")
    again = AppService(workspace=tmp_path / "ws", llm_factory=lambda c: scripted_llm(), experiment_guard=lambda: False)
    assert [i.id for i in again.list_investigations(incident_id="inc-001")] == [inv.id]
    assert again.list_investigations(mode="E3") == []
    assert again.record(inv.id).run_id == f"{inv.id}__E2b__r0"


def test_store_rejects_bad_ids(tmp_path):
    st = InvestigationStore(tmp_path)
    for bad in ("../x", "inv-1", "inv-20261125-zzzzzzzz", ""):
        with pytest.raises(KeyError):
            st.inv_dir(bad)


@pytest.mark.parametrize("raw,ok", [("app.log", "app.log"), ("../../etc/app.log", "app.log"),
                                    ("C:\\logs\\db server.log", "db-server.log"), ("x.txt", "x.txt")])
def test_sanitize_filename_ok(raw, ok):
    assert sanitize_filename(raw) == ok


@pytest.mark.parametrize("raw", [".hidden.log", "a.exe", "", "..", "incident.json", "logs/"])
def test_sanitize_filename_rejects(raw):
    with pytest.raises(ValueError):
        sanitize_filename(raw)


def test_cli_diagnose_investigations_report(tmp_path, monkeypatch, capsys):
    import logagent_rca.service as service
    monkeypatch.setattr(service, "OllamaClient", lambda cfg: scripted_llm())
    monkeypatch.setattr(service, "experiment_running", lambda: False)
    inp = dev_inputs()
    logs = []
    for name, content in inp["files"]:
        (tmp_path / name).write_bytes(content)
        logs += ["--log", str(tmp_path / name)]
    ws = str(tmp_path / "ws")
    rc = main(["diagnose", "--workspace", ws, *logs, "--incident-id", inp["incident_id"], "--description",
               inp["description"], "--time", inp["timestamp"], "--trigger-file", inp["trigger_file"],
               "--trigger-line", str(inp["trigger_line"]), "--trigger-component", inp["trigger_component"],
               "--mode", "E3"])
    out = capsys.readouterr().out
    assert rc == 0 and "Ranked root-cause hypotheses" in out and "run record:" in out
    assert main(["investigations", "--workspace", ws]) == 0
    inv_id = capsys.readouterr().out.split()[0]
    assert main(["report", "--workspace", ws, "--investigation", inv_id, "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["arm"] == "E3"


def test_cli_rejects_invalid_input(tmp_path, capsys):
    p = tmp_path / "a.log"
    p.write_text("2026-01-10T10:00:00Z ERROR svc boom\n")
    rc = main(["diagnose", "--workspace", str(tmp_path / "ws"), "--log", str(p), "--incident-id", "bad",
               "--description", "x", "--time", "2026-01-10T10:00:00Z", "--trigger-line", "1",
               "--trigger-component", "svc"])
    assert rc == 2 and "invalid" in capsys.readouterr().err


def test_research_cli_commands_unchanged():
    import inspect
    from logagent_rca import __main__ as m
    src = inspect.getsource(m._research)
    assert "run_experiment" in src and "analyze(cfg" in src
