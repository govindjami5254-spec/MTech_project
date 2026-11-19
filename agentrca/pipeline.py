"""End-to-end orchestration: logs -> index -> incidents -> investigation -> validated report."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .agent import Investigator
from .baselines import run_heuristic, run_rule, run_single, run_static
from .config import Config
from .ingest import LogIndex, load_logs
from .llm import make_llm
from .models import Incident
from .report import build_report, write_report
from .rules import Rule, detect, load_rules
from .safety import AuditLog

MODES = ("rule", "heuristic", "single", "static", "agent")


def prepare(cfg: Config) -> tuple[LogIndex, list[Rule], list[Incident]]:
    index = load_logs(cfg.logs, cfg.safety.redact)
    rules = load_rules(cfg.rules_file)
    return index, rules, detect(index, rules)


def investigate(cfg: Config, index: LogIndex, incident: Incident, mode: str,
                llm=None, out_dir: Optional[str] = None) -> dict:
    if mode not in MODES:
        raise ValueError(f"unknown mode '{mode}', choose from {MODES}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    run_id = f"{incident.id}-{mode}-{stamp}-{uuid.uuid4().hex[:6]}"
    run_dir = Path(out_dir or cfg.output_dir) / run_id if (out_dir or cfg.output_dir) else None
    audit = AuditLog(run_dir / "audit.jsonl" if run_dir else None, run_id)
    if mode in ("single", "static", "agent") and llm is None:
        llm = make_llm(cfg.llm)
    if mode in ("single", "static", "agent") and hasattr(llm, "check"):
        llm.check()                                   # raises LLMError with a clear message
    audit.log("run_start", mode=mode, incident=incident.id, model=cfg.llm.model,
              log_files=index.stats.get("files"), events=len(index.events),
              suspicious_lines=index.stats.get("suspicious"))
    if mode == "agent":
        inv = Investigator(cfg, index, llm, audit).run(incident)
    else:
        fn = {"rule": run_rule, "heuristic": run_heuristic, "single": run_single, "static": run_static}[mode]
        inv = fn(cfg, index, incident, llm, audit)
    report = build_report(run_id, mode, cfg, index, inv, audit)
    audit.log("run_end", hypotheses=len(report["hypotheses"]), validation=report["validation"])
    if run_dir:
        write_report(report, run_dir)
    return report
