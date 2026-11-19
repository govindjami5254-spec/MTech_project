"""RCA report assembly (JSON + Markdown)."""
from __future__ import annotations

import json
from pathlib import Path

from .agent import Investigation
from .config import Config
from .ingest import LogIndex, fmt_ts
from .safety import AuditLog
from .validator import validate


def build_report(run_id: str, mode: str, cfg: Config, index: LogIndex,
                 inv: Investigation, audit: AuditLog) -> dict:
    enforce = cfg.agent.validate and mode in ("agent", "single", "static")
    raw = inv.raw or {"hypotheses": [], "evidence_gaps": ["The model did not return a valid analysis."],
                      "recommendations": []}
    v = validate(raw, inv.store, index.components, enforce=enforce, has_gaps=bool(inv.gaps or raw.get("evidence_gaps")))
    cited = {i for h in v["hypotheses"] for c in h["claims"] for i in c["evidence_ids"]}
    gaps = list(inv.gaps)
    for g in raw.get("evidence_gaps", []):
        g = str(g).strip()
        if g and not any(c in g for c in index.components if any(f"'{c}'" in a for a in inv.gaps)):
            gaps.append(g)
    if not v["hypotheses"]:
        gaps.append("No hypothesis passed evidence-grounding validation.")
    m = inv.metrics.__dict__.copy()
    m["injection_flagged"] = audit.count("injection_suspected")
    report = {
        "run_id": run_id, "mode": mode,
        "incident": {"id": inv.incident.id, "rule": inv.incident.rule_id,
                     "description": inv.incident.description, "time": fmt_ts(inv.incident.ts),
                     "trigger": inv.incident.trigger.uid},
        "hypotheses": v["hypotheses"],
        "evidence_gaps": gaps,
        "recommendations": [str(r) for r in raw.get("recommendations", [])][:6],
        "validation": v["stats"],
        "evidence": [dict(e.to_dict(), cited=e.id in cited) for e in inv.store.all()],
        "metrics": m,
        "safety": {"blocked_tool_calls": audit.count("tool_blocked"),
                   "injection_suspected_lines": audit.count("injection_suspected"),
                   "read_only": True},
        "settings": {"model": cfg.llm.model, "num_ctx": cfg.llm.num_ctx, "temperature": cfg.llm.temperature,
                     "seed": cfg.llm.seed, "think": cfg.llm.think, "coverage_gate": cfg.agent.coverage_gate,
                     "validate": cfg.agent.validate, "max_steps": cfg.agent.max_steps},
    }
    return report


def to_markdown(r: dict) -> str:
    inc = r["incident"]
    out = [f"# RCA report - {inc['id']} ({r['mode']})", "",
           f"- Incident: {inc['description']} (rule `{inc['rule']}`) at {inc['time']}",
           f"- Model: {r['settings']['model']} | steps {r['metrics']['steps']} | tool calls "
           f"{r['metrics']['tool_calls']} | blocked {r['safety']['blocked_tool_calls']} | "
           f"wall {r['metrics']['wall_seconds']:.1f}s", "", "## Ranked hypotheses"]
    if not r["hypotheses"]:
        out.append("_None passed validation._")
    for h in r["hypotheses"]:
        out += ["", f"### {h['rank']}. {h['cause_component']} (confidence {h['confidence']})",
                h["cause_summary"], ""]
        for c in h["claims"]:
            out.append(f"- {c['text']}  \n  evidence: {', '.join(c['evidence_ids'])}")
    out += ["", "## Evidence gaps / uncertainty"] + [f"- {g}" for g in r["evidence_gaps"]] if r["evidence_gaps"] else []
    out += ["", "## Recommendations (for a human operator; AgentRCA never acts)"]
    out += [f"- {x}" for x in r["recommendations"]] or ["- (none)"]
    out += ["", "## Cited evidence"]
    for e in r["evidence"]:
        if e["cited"]:
            out.append(f"- [{e['id']}] `{e['source']}:{e['line_no']}` {e['ts']} {e['severity']} "
                       f"{e['component']}: {e['message']}")
    v = r["validation"]
    out += ["", "## Validation",
            f"- claims supported {v['claims_supported']}/{v['claims_total']} "
            f"(unsupported rate {v['unsupported_claim_rate']}), fabricated evidence IDs {v['fabricated_ids']}, "
            f"hypotheses dropped {v['hypotheses_dropped']}"]
    return "\n".join(out) + "\n"


def write_report(report: dict, run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(to_markdown(report), encoding="utf-8")
