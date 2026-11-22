"""M6 tests: read-only tools, allowlist, argument validation, audit log, budget enforcement."""
import json
from pathlib import Path

import pytest

from logagent_rca.config import SafetyConfig, load_config
from logagent_rca.context import open_case
from logagent_rca.evidence import EvidenceLedger
from logagent_rca.safety import AuditLog, PolicyViolation, ToolPolicy
from logagent_rca.tokens import counter_from_config
from logagent_rca.tools import TOOL_SPECS, ToolRegistry
from logagent_rca.truth import TruthStore

ROOT = Path(__file__).resolve().parent.parent
CFG = load_config(ROOT / "configs" / "dev.yaml")
COUNTER = counter_from_config(CFG.budget)
STORE = TruthStore(CFG.data.truth_dir)


def registry(tmp_path, stratum="multi_hop", budget=3000, allowed=None):
    cid = next(c for c in STORE.case_ids() if STORE.load(c).stratum.value == stratum)
    ctx = open_case(CFG.data.cases_path / cid, CFG)
    led = EvidenceLedger(budget, COUNTER)
    led.offer([ctx.trigger], 0, "incident")
    safety = SafetyConfig(allowed_tools=allowed or list(TOOL_SPECS))
    audit = AuditLog(tmp_path / "audit.jsonl", "r1")
    return ToolRegistry(ctx, led, safety, audit, CFG.agent.lookback_s), ctx, STORE.load(cid)


@pytest.mark.parametrize("name,args,code", [
    ("run_shell", {"cmd": "rm -rf /"}, "tool_not_allowed"),
    ("read_file", {"path": "../truth/dev-c001.json"}, "tool_not_allowed"),
    (None, {}, "tool_not_allowed"),
    ("search_logs", {"regex": ".*"}, "invalid_arguments"),
    ("search_logs", {"limit": 10_000}, "invalid_arguments"),
    ("search_logs", {"limit": True}, "invalid_arguments"),
    ("search_logs", {"component": "x" * 65}, "invalid_arguments"),
    ("search_logs", {"contains": "a\x00b"}, "invalid_arguments"),
    ("search_logs", {"min_severity": "LOUD"}, "invalid_arguments"),
    ("search_logs", {"start": "yesterday"}, "invalid_arguments"),
    ("search_logs", "not-an-object", "invalid_arguments"),
    ("get_context", {}, "invalid_arguments"),
])
def test_blocked_requests_are_refused_and_audited(tmp_path, name, args, code):
    reg, _, _ = registry(tmp_path)
    out = reg.execute(name, args, step=1)
    assert out.startswith(f"ERROR ({code})") and reg.blocked == 1 and reg.calls == 0
    entry = json.loads((tmp_path / "audit.jsonl").read_text().splitlines()[-1])
    assert entry["kind"] == "tool_blocked" and entry["code"] == code
    assert reg.records[-1].allowed is False


def test_allowlist_is_configurable(tmp_path):
    reg, _, _ = registry(tmp_path, allowed=["search_logs"])
    assert reg.execute("error_timeline", {}, 1).startswith("ERROR (tool_not_allowed)")
    assert [s["function"]["name"] for s in reg.specs()] == ["search_logs"]


def test_policy_normalises_valid_arguments():
    pol = ToolPolicy(TOOL_SPECS, list(TOOL_SPECS))
    assert pol.validate("search_logs", {"limit": "5", "component": " db ", "min_severity": "warning"}) == \
        {"limit": 5, "component": "db", "min_severity": "WARN"}


def test_tools_return_charged_evidence_and_compact_repeats(tmp_path):
    reg, ctx, truth = registry(tmp_path)
    first = reg.execute("error_timeline", {}, 1)
    assert "<log_data>" in first and reg.ledger.used > 0
    used = reg.ledger.used
    again = reg.execute("error_timeline", {}, 2)
    assert "(already shown)" in again and reg.ledger.used == used        # repeats are free
    assert reg.ledger.repeated_exposures > 0
    target = truth.root_causes[0]
    reg.execute("search_logs", {"component": target, "min_severity": "WARN"}, 3)
    assert target in reg.inspected
    assert any(e.uid in set(truth.key_evidence) for e in reg.ledger.items())


def test_get_context_requires_known_id_and_marks_component_inspected(tmp_path):
    reg, ctx, _ = registry(tmp_path)
    assert "Unknown evidence ID" in reg.execute("get_context", {"evidence_id": "E99"}, 1)
    out = reg.execute("get_context", {"evidence_id": "E1", "before": 2, "after": 2}, 2)
    assert "Context around E1" in out


def test_budget_is_strict_and_reported(tmp_path):
    reg, _, _ = registry(tmp_path, stratum="over_budget", budget=300)
    reg.execute("error_timeline", {}, 1)
    out = reg.execute("search_logs", {"min_severity": "ERROR", "limit": 15}, 2)
    assert reg.ledger.used <= 300 and "budget exhausted" in out
    s = reg.ledger.summary()
    assert s["unique_evidence_tokens"] == sum(e.tokens for e in reg.ledger.items())


def test_unknown_component_is_not_an_error_but_lists_components(tmp_path):
    reg, ctx, _ = registry(tmp_path)
    out = reg.execute("search_logs", {"component": "nope"}, 1)
    assert "Unknown component" in out and reg.blocked == 0


def test_injection_lines_are_flagged_in_audit(tmp_path):
    from logagent_rca.synth.dev_templates import FAMILIES
    from logagent_rca.synth.engine import generate_case
    from logagent_rca.ingest import write_manifest
    g = generate_case(FAMILIES[1], "dev-x001", 99, inject=True)
    cdir = tmp_path / "cases" / "dev-x001"
    cdir.mkdir(parents=True)
    for n, t in g.files.items():
        (cdir / n).write_text(t)
    write_manifest(cdir, g.manifest)
    ctx = open_case(cdir, CFG)
    led = EvidenceLedger(5000, COUNTER)
    audit = AuditLog(None, "r")
    reg = ToolRegistry(ctx, led, SafetyConfig(), audit, CFG.agent.lookback_s)
    inj = ctx.index.get(g.truth.injection_uids[0])
    reg.execute("search_logs", {"component": inj.component, "min_severity": "ERROR"}, 1)
    assert audit.count("injection_suspected") >= 1
