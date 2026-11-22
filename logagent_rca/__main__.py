"""Command line: ``python -m logagent_rca {run,analyze} --config CONFIG [...]``."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analyze import analyze
from .config import load_config, parse_override
from .runner import RunnerError, run_experiment
from .schemas import ArmId


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="logagent_rca")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run cases x arms x repeats (resumable)")
    r.add_argument("--config", required=True)
    r.add_argument("--cases", help="comma-separated case ids (default: all)")
    r.add_argument("--arms", help="comma-separated arms (default: config)")
    r.add_argument("--max-runs", type=int)
    r.add_argument("--allow-dirty", action="store_true")
    r.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    a = sub.add_parser("analyze", help="score and summarise an experiment directory")
    a.add_argument("--config", required=True)
    a.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    args = ap.parse_args(argv)
    cfg = load_config(args.config, dict(parse_override(s) for s in args.set))
    if args.cmd == "run":
        try:
            done = run_experiment(cfg, args.cases.split(",") if args.cases else None,
                                  [ArmId(x) for x in args.arms.split(",")] if args.arms else None,
                                  allow_dirty=args.allow_dirty, max_runs=args.max_runs,
                                  log=lambda m: print(m, flush=True))
        except RunnerError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(f"completed {len(done)} runs")
        return 0
    res = analyze(cfg, Path(cfg.experiment.output_dir))
    print(json.dumps({"primary": res["primary"], "summary": {k: v["correct"] for k, v in res["summary"].items()}},
                     indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
