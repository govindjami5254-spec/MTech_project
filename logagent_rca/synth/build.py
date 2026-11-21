"""Build, validate and checksum a synthetic split (M3).

    python -m logagent_rca.synth.build --split test --out data/synthetic --cases-per-family 3

Writes ``<out>/<split>/cases/<case_id>/`` (agent-visible), ``<out>/<split>/truth/`` (scorer only:
per-case truth, ``_families.json``, ``_summary.json``) and ``<out>/<split>/SHA256SUMS``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
from pathlib import Path

from ..config import IngestConfig
from ..ingest import load_case, write_manifest
from ..index import LogIndex
from ..schemas import Split, Stratum
from .engine import GENERATOR_VERSION, Family, generate_case, stable_seed

SPLIT_SEED = {Split.DEV: 11, Split.TEST: 29}


def families_for(split: Split) -> tuple[Family, ...]:
    if split == Split.DEV:
        from .dev_templates import FAMILIES
    else:
        from .test_templates import FAMILIES
    return FAMILIES


def plan(split: Split, per_family: int) -> list[tuple[str, Family, int, int]]:
    """(case_id, family, case_index, seed) with opaque, shuffled case ids."""
    slots = [(f, i) for f in families_for(split) for i in range(per_family)]
    random.Random(SPLIT_SEED[split]).shuffle(slots)
    return [(f"{split.value}-c{n:03d}", f, i, stable_seed(split.value, f.family_id, i, GENERATOR_VERSION))
            for n, (f, i) in enumerate(slots, 1)]


def validate_generated(case_dir: Path, truth, cfg: IngestConfig) -> dict:
    manifest, events, stats = load_case(case_dir, cfg)
    if stats.unparsed_lines or stats.bad_timestamps or stats.bad_components:
        raise AssertionError(f"{case_dir.name}: unparsed={stats.unparsed_lines}")
    files = sorted(p.name for p in case_dir.iterdir())
    if files != sorted(["incident.json", *manifest.log_files]):
        raise AssertionError(f"{case_dir.name}: unexpected files {files}")
    idx = LogIndex(events)
    for uid in truth.relevant_evidence + truth.injection_uids:
        if idx.get(uid) is None:
            raise AssertionError(f"{case_dir.name}: truth uid {uid} missing from logs")
    for uid in truth.key_evidence:
        if idx.get(uid).component not in truth.root_causes:
            raise AssertionError(f"{case_dir.name}: key evidence outside root causes")
    comps = set(idx.components)
    if not set(truth.propagation_path) <= comps or not set(truth.root_causes) <= comps:
        raise AssertionError(f"{case_dir.name}: unknown component in truth")
    warn_plus = [e for e in events if e.severity.rank >= 30]
    return {"events": len(events), "warn_plus": len(warn_plus), "components": len(comps)}


def build(split: Split, out: Path, per_family: int) -> dict:
    root = out / split.value
    if root.exists():
        shutil.rmtree(root)
    cases_dir, truth_dir = root / "cases", root / "truth"
    cases_dir.mkdir(parents=True)
    truth_dir.mkdir(parents=True)
    cfg = IngestConfig()
    summary, families = [], {}
    for case_id, fam, i, seed in plan(split, per_family):
        g = generate_case(fam, case_id, seed)
        cdir = cases_dir / case_id
        cdir.mkdir()
        for name, text in g.files.items():
            (cdir / name).write_text(text, encoding="utf-8")
        write_manifest(cdir, g.manifest)
        (truth_dir / f"{case_id}.json").write_text(
            json.dumps(g.truth.model_dump(mode="json"), indent=2), encoding="utf-8")
        stats = validate_generated(cdir, g.truth, cfg)
        summary.append({"case_id": case_id, "family_id": fam.family_id, "stratum": fam.stratum.value,
                        "hops": len(fam.topology.path_to(fam.target)) - 1, **stats})
        families.setdefault(fam.family_id, {
            "topology": fam.topology.id, "vocab": fam.vocab.id, "stratum": fam.stratum.value,
            "fault_type": fam.fault_type, "target": fam.target, "second_fault": fam.second_fault,
            "second_target": fam.second_target, "cases": []})["cases"].append(case_id)
    meta = {"generator_version": GENERATOR_VERSION, "split": split.value, "cases": len(summary),
            "families": len(families), "cases_per_family": per_family}
    (truth_dir / "_families.json").write_text(json.dumps({**meta, "families": families}, indent=2))
    (truth_dir / "_summary.json").write_text(json.dumps({**meta, "per_case": summary}, indent=2))
    sums = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "SHA256SUMS":
            sums.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root).as_posix()}")
    (root / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    return meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=[s.value for s in Split], required=True)
    ap.add_argument("--out", default="data/synthetic")
    ap.add_argument("--cases-per-family", type=int, default=3)
    a = ap.parse_args(argv)
    print(json.dumps(build(Split(a.split), Path(a.out), a.cases_per_family)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
