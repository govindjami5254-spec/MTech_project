"""Experiment runner (M10): cases x arms x repeats, resumable, fully recorded.

* Order: repeat-major (all cases and arms for repeat 0 first), so a partial run is still balanced.
* Run ids are deterministic (``<case>__<arm>__r<k>``); existing records are skipped (resumable).
* E1/E1f are deterministic and run once. A3 is never run: it is scored from E3's raw report.
* Each run stores a validated ``RunRecord`` (JSON), an audit log (JSONL) and, for LLM arms, the
  full message transcript. Ground truth is never loaded here.
* Before running, the frozen split is verified against its SHA256SUMS; the test split also requires a
  clean git working tree so that every record names the exact code commit.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .agent import run_e3
from .config import Config, config_hash
from .context import ArmResult, open_case
from .coverage import make_gate
from .e1 import run_e1, run_e1_floor
from .e2b import run_e2b
from .llm import LLMError, OllamaClient
from .resources import ResourceSampler
from .safety import AuditLog
from .schemas import ArmId, RunMetrics, RunRecord, RunStatus, Split
from .tokens import counter_from_config
from .validator import validate_report

LLM_ARMS = (ArmId.E2B, ArmId.E3, ArmId.A2)
DETERMINISTIC = (ArmId.E1, ArmId.E1F)


class RunnerError(RuntimeError):
    pass


def git_commit(root: Path) -> tuple[Optional[str], bool]:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
                             check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root,
                                    capture_output=True, text=True, check=True).stdout.strip())
        return sha, dirty
    except (OSError, subprocess.CalledProcessError):
        return None, True


def verify_split(cfg: Config) -> None:
    if not cfg.data.sums_file:
        return
    sums = Path(cfg.data.sums_file)
    if cfg.data.sums_sha256 and hashlib.sha256(sums.read_bytes()).hexdigest() != cfg.data.sums_sha256:
        raise RunnerError(f"{sums} does not match the frozen digest")
    root = sums.parent
    for line in sums.read_text().splitlines():
        digest, rel = line.split("  ", 1)
        if hashlib.sha256((root / rel).read_bytes()).hexdigest() != digest:
            raise RunnerError(f"frozen data changed: {rel}")


def planned_runs(cfg: Config, case_ids: list[str], arms: Optional[Iterable[ArmId]] = None):
    arms = [a for a in (arms or cfg.experiment.arms) if a != ArmId.A3]
    if ArmId.E1 in arms and ArmId.E1F not in arms:
        arms.insert(arms.index(ArmId.E1) + 1, ArmId.E1F)
    for rep in range(cfg.experiment.repeats):
        for cid in case_ids:
            for arm in arms:
                if arm in DETERMINISTIC and rep > 0:
                    continue
                yield cid, arm, rep


def _run_arm(arm: ArmId, ctx, cfg: Config, llm, counter, seed: int, audit: AuditLog) -> ArmResult:
    B = cfg.budget.evidence_token_budget
    if arm == ArmId.E1:
        return run_e1(ctx, counter, B, cfg.agent.lookback_s)
    if arm == ArmId.E1F:
        return run_e1_floor(ctx, counter, B)
    if arm == ArmId.E2B:
        return run_e2b(ctx, cfg, llm, counter, seed)
    gate = make_gate(cfg.agent.lookback_s) if (arm == ArmId.E3 and cfg.agent.coverage_gate) else None
    return run_e3(ctx, cfg, llm, counter, seed, audit, gate=gate)


def run_one(cfg: Config, case_id: str, arm: ArmId, rep: int, out: Path, llm, counter,
            model_info_cache: dict, commit: Optional[str]) -> RunRecord:
    run_id = f"{case_id}__{arm.value}__r{rep}"
    seed = cfg.experiment.seed_for(rep)
    audit = AuditLog(out / "audit" / f"{run_id}.jsonl", run_id)
    ctx = open_case(cfg.data.cases_path / case_id, cfg)
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    model = None
    if arm in LLM_ARMS:
        if seed not in model_info_cache:
            model_info_cache[seed] = llm.model_info(seed)
        model = model_info_cache[seed]
    attempts = 0
    while True:
        attempts += 1
        with ResourceSampler() as rs:
            res = _run_arm(arm, ctx, cfg, llm, counter, seed, audit)
        infra = res.report_raw is None and res.error and ("Ollama request" in res.error or "llm_error" in res.error)
        if not infra or attempts >= 3:
            break
        audit.log("runner_retry", attempt=attempts, error=res.error)
    wall = time.monotonic() - t0
    validated, vstats = (validate_report(res.report_raw, res.ledger, ctx.index.components,
                                         cfg.validator.min_overlap_tokens) if res.report_raw else (None, None))
    s = res.ledger.summary()
    metrics = RunMetrics(evidence_token_budget=s["evidence_token_budget"],
                         unique_evidence_tokens=s["unique_evidence_tokens"],
                         unique_evidence_items=s["unique_evidence_items"],
                         repeated_exposures=s["repeated_exposures"],
                         repeated_exposure_tokens=s["repeated_exposure_tokens"],
                         llm_calls=res.llm.calls, prompt_tokens_total=res.llm.prompt_tokens,
                         output_tokens_total=res.llm.output_tokens, llm_seconds=round(res.llm.seconds, 3),
                         wall_seconds=round(wall, 3), steps=res.steps,
                         tool_calls=sum(1 for t in res.tool_calls if t.allowed),
                         blocked_tool_calls=res.blocked_calls, gate_rounds=res.gate_rounds,
                         parse_failures=res.llm.parse_failures, normalised_fields=res.llm.normalised_fields,
                         **({k: v for k, v in rs.as_dict().items()} if arm in LLM_ARMS else {}))
    rec = RunRecord(run_id=run_id, case_id=case_id, split=ctx.manifest.split, arm=arm, repeat=rep,
                    config_hash=config_hash(cfg), code_commit=commit, model=model, started_at=started,
                    status=res.status, error=(res.error or None) and str(res.error)[:500],
                    report_raw=res.report_raw, report_validated=validated, validation=vstats,
                    evidence=res.ledger.items(), tool_calls=res.tool_calls, metrics=metrics)
    (out / "runs").mkdir(parents=True, exist_ok=True)
    tmp = out / "runs" / f"{run_id}.json.tmp"
    tmp.write_text(rec.model_dump_json(indent=1), encoding="utf-8")
    tmp.replace(out / "runs" / f"{run_id}.json")                 # atomic: a crash never leaves half a record
    if "messages" in res.notes:
        (out / "transcripts").mkdir(parents=True, exist_ok=True)
        (out / "transcripts" / f"{run_id}.json").write_text(
            json.dumps({"run_id": run_id, "notes": {k: v for k, v in res.notes.items() if k != "messages"},
                        "messages": res.notes["messages"]}, indent=1, default=str), encoding="utf-8")
    with (out / "index.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"run_id": run_id, "status": rec.status.value, "wall_s": metrics.wall_seconds,
                             "finished_at": datetime.now(timezone.utc).isoformat()}) + "\n")
    return rec


def run_experiment(cfg: Config, case_ids: Optional[list[str]] = None, arms: Optional[list[ArmId]] = None,
                   llm=None, allow_dirty: bool = False, repo_root: Path = Path("."),
                   max_runs: Optional[int] = None, log=print) -> list[str]:
    verify_split(cfg)
    commit, dirty = git_commit(repo_root)
    if cfg.experiment.split == Split.TEST and dirty and not allow_dirty:
        raise RunnerError("test runs require a clean git working tree (commit first)")
    out = Path(cfg.experiment.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps({"config_hash": config_hash(cfg), "code_commit": commit,
                                                 "dirty": dirty, "config": cfg.model_dump(mode="json")},
                                                indent=1))
    all_cases = sorted(p.name for p in cfg.data.cases_path.iterdir() if p.is_dir())
    case_ids = case_ids or all_cases
    unknown = set(case_ids) - set(all_cases)
    if unknown:
        raise RunnerError(f"unknown cases: {sorted(unknown)}")
    counter = counter_from_config(cfg.budget)
    llm = llm or OllamaClient(cfg.llm)
    done, cache = [], {}
    plan = list(planned_runs(cfg, case_ids, arms))
    for n, (cid, arm, rep) in enumerate(plan, 1):
        run_id = f"{cid}__{arm.value}__r{rep}"
        if (out / "runs" / f"{run_id}.json").exists():
            continue
        if max_runs is not None and len(done) >= max_runs:
            break
        rec = run_one(cfg, cid, arm, rep, out, llm, counter, cache, commit)
        done.append(run_id)
        log(f"[{n}/{len(plan)}] {run_id} {rec.status.value} {rec.metrics.wall_seconds:.0f}s")
    return done
