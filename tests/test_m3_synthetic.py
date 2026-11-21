"""M3 tests: synthetic generator v2, dev/test independence, truth separation, frozen test split."""
import json
import re
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pytest

from logagent_rca.config import IngestConfig, load_config
from logagent_rca.evidence import render_evidence
from logagent_rca.ingest import load_case
from logagent_rca.schemas import Split, Stratum
from logagent_rca.synth import dev_templates, test_templates
from logagent_rca.synth.build import build, families_for, plan
from logagent_rca.synth.engine import generate_case
from logagent_rca.tokens import counter_from_config
from logagent_rca.truth import TruthStore

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "synthetic"
CFG = load_config(ROOT / "configs" / "dev.yaml")
B = CFG.budget.evidence_token_budget
TRUTH_KEYS = {"root_causes", "family_id", "stratum", "fault_type", "key_evidence",
              "relevant_evidence", "propagation_path", "expected_abstain", "decoy_component"}


def _cases(split):
    store = TruthStore(DATA / split / "truth")
    for cid in store.case_ids():
        cdir = DATA / split / "cases" / cid
        manifest, events, _ = load_case(cdir, IngestConfig())
        yield cid, cdir, manifest, events, store.load(cid)


# ------------------------------------------------------------- independence
def _names(fams):
    topo = {f.topology.id for f in fams}
    vocab = {f.vocab.id for f in fams}
    comps = {c for f in fams for c in f.topology.components}
    phrases = {m for f in fams for m in (*f.vocab.ok, *f.vocab.dep_errors, *f.vocab.entry_5xx)}
    return topo, vocab, comps, phrases


def test_dev_and_test_templates_are_disjoint():
    d, t = _names(dev_templates.FAMILIES), _names(test_templates.FAMILIES)
    for a, b in zip(d, t):
        assert not (a & b), f"overlap between dev and test: {a & b}"
    assert not ({f.family_id for f in dev_templates.FAMILIES} & {f.family_id for f in test_templates.FAMILIES})


def test_split_sizes_and_strata():
    tf = families_for(Split.TEST)
    assert len(tf) == 20 and len(families_for(Split.DEV)) == 6
    counts = Counter(f.stratum for f in tf)
    assert counts == {Stratum.EASY: 3, Stratum.MULTI_HOP: 4, Stratum.DISTRACTOR: 4,
                      Stratum.OVER_BUDGET: 4, Stratum.CONCURRENT: 2, Stratum.INSUFFICIENT: 3}
    assert set(Counter(f.stratum for f in families_for(Split.DEV))) == set(Stratum)
    p = plan(Split.TEST, 3)
    assert len(p) == 60 and len({cid for cid, *_ in p}) == 60
    assert Counter(f.family_id for _, f, _, _ in p) == {f.family_id: 3 for f in tf}


# ------------------------------------------------------------- determinism / freeze
def test_generation_is_deterministic():
    fam = test_templates.FAMILIES[4]
    a = generate_case(fam, "x-c001", 12345)
    b = generate_case(fam, "x-c001", 12345)
    c = generate_case(fam, "x-c001", 12346)
    assert a.files == b.files and a.truth == b.truth
    assert a.files != c.files


@pytest.mark.parametrize("split", ["dev", "test"])
def test_committed_split_matches_regeneration(split, tmp_path):
    build(Split(split), tmp_path, 3)
    assert (tmp_path / split / "SHA256SUMS").read_text() == (DATA / split / "SHA256SUMS").read_text()


# ------------------------------------------------------------- truth separation
@pytest.mark.parametrize("split", ["dev", "test"])
def test_case_bundles_contain_no_ground_truth(split):
    fam_ids = {f.family_id for f in families_for(Split(split))}
    for cid, cdir, manifest, events, truth in _cases(split):
        files = {p.name for p in cdir.iterdir()}
        assert files == {"incident.json", *manifest.log_files}
        raw = json.loads((cdir / "incident.json").read_text())
        assert not (TRUTH_KEYS & set(raw)) and not (TRUTH_KEYS & set(raw["incident"]))
        assert not any(f in cid for f in fam_ids) and truth.fault_type.split("+")[0] not in cid
        text = "\n".join((cdir / f).read_text() for f in manifest.log_files)
        assert not re.search(rf"\b{truth.family_id}\b", text)
    assert not (DATA / split / "cases").joinpath("_families.json").exists()


def test_config_dirs_are_disjoint_for_generated_data():
    assert not CFG.data.truth_path.is_relative_to(CFG.data.cases_path)
    assert TruthStore(CFG.data.truth_dir).case_ids()[0] == "dev-c001"


# ------------------------------------------------------------- truth consistency and strata
@pytest.mark.parametrize("split", ["dev", "test"])
def test_truth_resolves_and_strata_hold(split):
    for cid, cdir, manifest, events, truth in _cases(split):
        by_uid = {e.uid: e for e in events}
        assert manifest.incident.trigger_uid in by_uid
        assert manifest.incident.trigger_component == by_uid[manifest.incident.trigger_uid].component
        assert all(u in by_uid for u in truth.relevant_evidence)
        assert {by_uid[u].component for u in truth.key_evidence} == set(truth.root_causes)
        if truth.stratum == Stratum.EASY:
            assert len(truth.propagation_path) == 2
        if truth.stratum == Stratum.MULTI_HOP:
            assert len(truth.propagation_path) >= 4
        if truth.stratum == Stratum.CONCURRENT:
            assert len(truth.root_causes) == 2
        if truth.stratum == Stratum.INSUFFICIENT:
            assert truth.expected_abstain and not truth.key_evidence
            # the silent component never logs a problem itself
            fam = next(f for f in families_for(Split(split)) if f.family_id == truth.family_id)
            assert not [e for e in events if e.component == fam.target and e.severity.rank >= 40]
        # root cause precedes the incident
        if truth.key_evidence:
            assert min(by_uid[u].ts for u in truth.key_evidence) <= manifest.incident.ts


@pytest.mark.parametrize("split", ["dev", "test"])
def test_distractors_precede_the_root_cause(split):
    for cid, cdir, manifest, events, truth in _cases(split):
        if truth.stratum != Stratum.DISTRACTOR:
            continue
        first_root = min(e.ts for e in events if e.uid in set(truth.key_evidence))
        window = [e for e in events if e.severity.rank >= 30
                  and manifest.incident.ts - timedelta(seconds=600) <= e.ts <= manifest.incident.ts]
        earliest = min(window, key=lambda e: e.ts)
        assert earliest.component not in truth.root_causes and earliest.ts < first_root


@pytest.mark.parametrize("split", ["dev", "test"])
def test_over_budget_exceeds_b_while_key_evidence_fits(split):
    counter = counter_from_config(CFG.budget.model_copy(
        update={"tokenizer_file": str(ROOT / CFG.budget.tokenizer_file)}))
    seen = 0
    for cid, cdir, manifest, events, truth in _cases(split):
        warn_tokens = sum(counter.count(render_evidence("E100", e) + "\n")
                          for e in events if e.severity.rank >= 30)
        key_tokens = sum(counter.count(render_evidence("E100", e) + "\n")
                         for e in events if e.uid in set(truth.key_evidence))
        if truth.stratum == Stratum.OVER_BUDGET:
            seen += 1
            assert warn_tokens > 3 * B, f"{cid}: only {warn_tokens} WARN+ tokens"
        assert key_tokens <= B // 4
    assert seen == (12 if split == "test" else 3)
