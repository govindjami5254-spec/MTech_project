"""Command line: ``python -m logagent_rca <command>``.

Research (unchanged): ``run`` (experiment) and ``analyze`` (scoring against ground truth).
Application (shared services, same engine as the web UI): ``diagnose``, ``investigations``, ``report``, ``serve``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analyze import analyze
from .config import load_config, parse_override
from .runner import RunnerError, run_experiment
from .schemas import ArmId


def _research(args) -> int:
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


def _service(args):
    from .service import AppService
    return AppService(config_path=args.config, workspace=args.workspace)


def _app(args) -> int:
    from .report_render import to_markdown
    from .service import AnalysisRefused, ValidationProblem
    svc = _service(args)
    if args.cmd == "diagnose":
        files = []
        for p in args.log:
            path = Path(p)
            if not path.is_file():
                print(f"ERROR: not a file: {p}", file=sys.stderr)
                return 2
            files.append((path.name, path.read_bytes()))
        try:
            inv = svc.create_investigation(files, args.incident_id, args.description, args.time,
                                           args.trigger_file or Path(args.log[0]).name, args.trigger_line,
                                           args.trigger_component, rule_id=args.rule_id, owner="cli")
        except ValidationProblem as vp:
            for k, v in vp.errors.items():
                print(f"invalid {k}: {v}", file=sys.stderr)
            return 2
        for w in inv.warnings:
            print(f"warning: {w}", file=sys.stderr)
        print(f"investigation {inv.id} created; running {args.mode} with {svc.base_cfg.llm.model} "
              f"(evidence budget {svc.base_cfg.budget.evidence_token_budget} tokens)...", flush=True)
        try:
            rec = svc.analyze(inv.id, args.mode, requested_by="cli")
        except AnalysisRefused as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 3
        if rec is None:
            a = svc.store.load(inv.id).analyses[-1]
            print(f"ERROR: analysis {a.status}: {a.error}", file=sys.stderr)
            return 3
        print(to_markdown(rec, svc.manifest(inv.id)))
        print(f"run record: {svc.store.record_path(inv.id, rec.run_id)}")
        return 0 if rec.status.value == "ok" else 3
    if args.cmd == "investigations":
        rows = svc.list_investigations(incident_id=args.incident_id, mode=args.mode)
        for inv in rows:
            modes = ",".join(f"{a.mode}:{a.status}" for a in inv.analyses) or "-"
            print(f"{inv.id}  {inv.created_at:%Y-%m-%d %H:%M}  {inv.incident.id}  {modes}  {inv.incident.description[:60]}")
        print(f"{len(rows)} investigation(s)")
        return 0
    if args.cmd == "report":
        try:
            rec = svc.record(args.investigation, args.run)
        except KeyError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(rec.model_dump_json(indent=1) if args.format == "json" else to_markdown(rec, svc.manifest(args.investigation)))
        return 0
    raise AssertionError(args.cmd)


def _serve(args) -> int:
    from .web.app import serve
    return serve(config_path=args.config, workspace=args.workspace, host=args.host, port=args.port,
                 auth_file=args.auth_file)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="logagent_rca")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="research: run cases x arms x repeats (resumable)")
    r.add_argument("--config", required=True)
    r.add_argument("--cases", help="comma-separated case ids (default: all)")
    r.add_argument("--arms", help="comma-separated arms (default: config)")
    r.add_argument("--max-runs", type=int)
    r.add_argument("--allow-dirty", action="store_true")
    r.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    a = sub.add_parser("analyze", help="research: score and summarise an experiment directory")
    a.add_argument("--config", required=True)
    a.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")

    def app_common(p):
        p.add_argument("--config", default="configs/app.yaml", help="application config (default: configs/app.yaml)")
        p.add_argument("--workspace", help="workspace directory (default: from config)")

    d = sub.add_parser("diagnose", help="diagnose one incident from log files (same engine as the web UI)")
    app_common(d)
    d.add_argument("--log", action="append", required=True, help="log file (repeatable)")
    d.add_argument("--incident-id", required=True, help="e.g. INC-001 (INC- followed by 3-6 digits)")
    d.add_argument("--description", required=True)
    d.add_argument("--time", required=True, help="incident time with zone, e.g. 2026-01-10T10:05:00Z")
    d.add_argument("--trigger-file", help="file containing the trigger line (default: first --log)")
    d.add_argument("--trigger-line", required=True, type=int, help="1-based line number of the trigger event")
    d.add_argument("--trigger-component", required=True)
    d.add_argument("--rule-id", default=None)
    d.add_argument("--mode", choices=["E2b", "E3"], default="E3")
    lst = sub.add_parser("investigations", help="list stored investigations")
    app_common(lst)
    lst.add_argument("--incident-id")
    lst.add_argument("--mode", choices=["E2b", "E3"])
    rp = sub.add_parser("report", help="print a stored RCA report")
    app_common(rp)
    rp.add_argument("--investigation", required=True)
    rp.add_argument("--run", help="run id (default: latest completed)")
    rp.add_argument("--format", choices=["md", "json"], default="md")
    sv = sub.add_parser("serve", help="start the web application")
    app_common(sv)
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--auth-file", help="users file (required when binding to a non-loopback address)")
    args = ap.parse_args(argv)
    if args.cmd in ("run", "analyze"):
        return _research(args)
    if args.cmd == "serve":
        return _serve(args)
    return _app(args)


if __name__ == "__main__":
    raise SystemExit(main())
