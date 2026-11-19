"""Command line interface: synth | run | eval."""
from __future__ import annotations

import argparse
import json
import sys

from .config import load_config, parse_override_value
from .pipeline import MODES, investigate, prepare
from .synth import FAULTS, generate


def _overrides(items) -> dict:
    out = {}
    for item in items or []:
        key, _, val = item.partition("=")
        out[key.strip()] = parse_override_value(val)
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="agentrca", description="Agentic, read-only RCA for distributed-system logs")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("synth", help="generate a synthetic scenario with ground truth")
    s.add_argument("--out", required=True)
    s.add_argument("--fault", default="disk_full", choices=FAULTS)
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--target", help="component to fault (default: random from seed)")
    s.add_argument("--inject", action="store_true", help="plant a prompt-injection line in the logs")

    r = sub.add_parser("run", help="detect incidents and investigate one")
    r.add_argument("--config", default="config.yaml")
    r.add_argument("--logs", help="log directory or file (overrides logs.root)")
    r.add_argument("--mode", default="agent", choices=MODES)
    r.add_argument("--incident", help="incident id (default: highest priority)")
    r.add_argument("--list", action="store_true", help="only list detected incidents")
    r.add_argument("--set", action="append", metavar="KEY=VALUE", help="override config, e.g. agent.coverage_gate=false")

    e = sub.add_parser("eval", help="compare arms on generated scenarios")
    e.add_argument("--config", default="config.yaml")
    e.add_argument("--modes", default="rule,heuristic,single,static,agent")
    e.add_argument("--faults", default=",".join(FAULTS))
    e.add_argument("--seeds", default="1")
    e.add_argument("--repeats", type=int, default=1)
    e.add_argument("--inject", action="store_true")
    e.add_argument("--work-dir")
    e.add_argument("--set", action="append", metavar="KEY=VALUE")

    a = p.parse_args(argv)
    from .llm import LLMError
    try:
        return _dispatch(a)
    except LLMError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def _dispatch(a) -> int:

    if a.cmd == "synth":
        truth = generate(a.out, a.fault, a.seed, target=a.target, inject=a.inject)
        print(json.dumps(truth, indent=2))
        return 0

    cfg = load_config(a.config, _overrides(a.set))
    if a.cmd == "run":
        if a.logs:
            cfg.logs.root = a.logs
        index, _, incidents = prepare(cfg)
        print(f"Ingested {len(index.events)} events from {index.stats['files']} files; "
              f"{len(incidents)} incident(s) detected.")
        for i in incidents:
            print(f"  {i.id} [{i.rule_id}] {i.description} @ {i.ts.isoformat()}")
        if a.list or not incidents:
            return 0
        inc = next((i for i in incidents if i.id == a.incident), incidents[0])
        report = investigate(cfg, index, inc, a.mode)
        print(f"\nReport written to {cfg.output_dir}/{report['run_id']}/")
        for h in report["hypotheses"]:
            print(f"  #{h['rank']} {h['cause_component']} (conf {h['confidence']}): {h['cause_summary']}")
        m = report["metrics"]
        print(f"  steps={m['steps']} tool_calls={m['tool_calls']} blocked={report['safety']['blocked_tool_calls']} "
              f"tokens={m['tokens_in']}+{m['tokens_out']} wall={m['wall_seconds']:.1f}s")
        return 0

    from .eval import run_eval, summarize
    rows = run_eval(cfg, a.modes.split(","), a.faults.split(","), [int(x) for x in a.seeds.split(",")],
                    a.repeats, a.inject, a.work_dir)
    print(summarize(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
