"""M4 tests: E1 rule-based RCA and the log-free floor."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from logagent_rca.config import load_config
from logagent_rca.context import CaseContext, open_case
from logagent_rca.e1 import run_e1, run_e1_floor
from logagent_rca.index import LogIndex
from logagent_rca.ingest import IngestStats
from logagent_rca.schemas import CaseManifest, Incident, LogEvent
from logagent_rca.truth import TruthStore

ROOT = Path(__file__).resolve().parent.parent
CFG = load_config(ROOT / "configs" / "dev.yaml")
T0 = datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc)


class Fixed:
    def count(self, t):
        return 10 if t else 0

    provenance = {}


def ctx_from(lines, trigger_uid):
    evs = []
    for comp, n, sec, sev, msg in lines:
        evs.append(LogEvent(uid=f"{comp}.log:{n}", ts=T0 + timedelta(seconds=sec), severity=sev,
                            component=comp, message=msg, source=f"{comp}.log", line_no=n))
    idx = LogIndex(evs)
    trig = idx.get(trigger_uid)
    inc = Incident(id="INC-001", rule_id="entry-5xx", description="x", ts=trig.ts,
                   trigger_uid=trigger_uid, trigger_component=trig.component)
    m = CaseManifest(case_id="c1", split="dev", incident=inc, log_files=sorted({e.source for e in evs}))
    return CaseContext(Path("."), m, idx, IngestStats())


CHAIN = [("gw", 1, 50, "ERROR", "503 from orders"), ("orders", 1, 40, "ERROR", "call to db failed"),
         ("db", 1, 30, "ERROR", "No space left on device"), ("cache", 1, 10, "ERROR", "unrelated cache error"),
         ("gw", 2, 52, "ERROR", "503 from orders again")]


def test_follows_dependency_chain_to_root_cause():
    r = run_e1(ctx_from(CHAIN, "gw.log:1"), Fixed(), 3000, 600)
    hyp = r.report_raw.hypotheses[0]
    assert r.notes["chain"] == ["gw", "orders", "db"] and hyp.cause_component == "db"
    assert "disk full" in hyp.cause_summary
    ids = {e.id for e in r.ledger.items()}
    assert all(i in ids for c in hyp.claims for i in c.evidence_ids)


def test_silent_dependency_abstains():
    lines = [("gw", 1, 50, "ERROR", "503 from orders"), ("orders", 1, 40, "ERROR", "timeout calling db"),
             ("db", 1, 30, "INFO", "healthy")]
    r = run_e1(ctx_from(lines, "gw.log:1"), Fixed(), 3000, 600)
    assert r.report_raw.abstained and r.notes["rule"] == "silent_dependency"


def test_no_dependency_mention_blames_incident_component():
    r = run_e1(ctx_from([("gw", 1, 50, "ERROR", "internal failure")], "gw.log:1"), Fixed(), 3000, 600)
    assert r.report_raw.hypotheses[0].cause_component == "gw"


def test_cycle_terminates():
    lines = [("a", 1, 50, "ERROR", "b failed"), ("b", 1, 40, "ERROR", "a failed")]
    r = run_e1(ctx_from(lines, "a.log:1"), Fixed(), 3000, 600)
    assert r.notes["chain"] == ["a", "b"]


def test_e1_respects_budget():
    r = run_e1(ctx_from(CHAIN, "gw.log:1"), Fixed(), 25, 600)       # room for 2 items only
    assert r.ledger.used <= 25 and len(r.ledger.items()) == 2


def test_floor_ignores_logs():
    r = run_e1_floor(ctx_from(CHAIN, "gw.log:1"), Fixed(), 3000)
    assert r.report_raw.hypotheses[0].cause_component == "gw" and len(r.ledger.items()) == 1


def test_e1_on_dev_split_outputs_valid_reports():
    from logagent_rca.tokens import counter_from_config
    counter = counter_from_config(CFG.budget)
    store = TruthStore(CFG.data.truth_dir)
    for cid in store.case_ids():
        ctx = open_case(CFG.data.cases_path / cid, CFG)
        r = run_e1(ctx, counter, CFG.budget.evidence_token_budget, CFG.agent.lookback_s)
        assert r.ledger.used <= CFG.budget.evidence_token_budget
        ids = {e.id for e in r.ledger.items()}
        assert all(i in ids for h in r.report_raw.hypotheses for c in h.claims for i in c.evidence_ids)
