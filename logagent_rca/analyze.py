"""Analysis of a completed (or partial) experiment directory (M10)."""
from __future__ import annotations

import json
from pathlib import Path

from .config import Config
from .metrics import score_all
from .schemas import RunRecord
from .stats import arm_summary, holm, paired
from .truth import TruthStore

PRIMARY = ("correct", "E3", "E2b")
SECONDARY = [("correct", "E3", "E1"), ("correct", "E2b", "E1"), ("correct", "E3", "A2"),
             ("correct", "E3", "A3"), ("unsupported_claim_rate", "E3", "E2b"),
             ("unsupported_claim_rate", "A3", "E3"), ("grounded", "E3", "E2b"),
             ("evidence_coverage", "E3", "E2b")]
HEADER = ("EXPLORATORY ANALYSIS - underpowered design (D-024). Effects are reported with 95% cluster-"
          "bootstrap CIs and family-level permutation p-values as descriptive statistics only; no claim of "
          "statistical significance is made.")


def load_records(out_dir: Path) -> list[RunRecord]:
    return [RunRecord.model_validate_json(p.read_text(encoding="utf-8"))
            for p in sorted((out_dir / "runs").glob("*.json"))]


def analyze(cfg: Config, out_dir: Path, n_boot: int = 10_000) -> dict:
    records = load_records(out_dir)
    store = TruthStore(cfg.data.truth_dir)
    truths = {cid: store.load(cid) for cid in {r.case_id for r in records}}
    rows = score_all(records, truths)
    primary = paired(rows, *PRIMARY, n_boot=n_boot)
    secondary = {f"{m}:{a}-{b}": paired(rows, m, a, b, n_boot=n_boot) for m, a, b in SECONDARY}
    adj = holm({k: v["perm_p"] for k, v in secondary.items() if v.get("n_cases")})
    for k, v in secondary.items():
        if k in adj:
            v["perm_p_holm"] = adj[k]
    strata = {s: paired(rows, *PRIMARY, n_boot=2000, stratum=s) for s in sorted({r["stratum"] for r in rows})}
    result = {"note": HEADER, "n_records": len(records), "summary": arm_summary(rows),
              "primary": primary, "primary_by_stratum": strata, "secondary": secondary,
              "code_commits": sorted({r.code_commit or "unknown" for r in records}),
              "config_hashes": sorted({r.config_hash for r in records})}
    (out_dir / "analysis").mkdir(exist_ok=True)
    (out_dir / "analysis" / "scores.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (out_dir / "analysis" / "analysis.json").write_text(json.dumps(result, indent=1))
    (out_dir / "analysis" / "analysis.md").write_text(to_markdown(result))
    return result


def _f(x, pct=False):
    if x is None:
        return "–"
    return f"{100 * x:.1f}%" if pct else (f"{x:.0f}" if abs(x) >= 100 else f"{x:.2f}")


def to_markdown(res: dict) -> str:
    lines = [f"> {res['note']}", "", f"Records: {res['n_records']}; code commits: {', '.join(res['code_commits'])}", "",
             "| Arm | Runs | Failed | Correct | Top-3 | Grounded | Evidence prec. | Evidence cov. | Unsupported claims | Median wall s | Median prompt tok | Median output tok | Median CPU s | Peak RSS MB | Median B used | Median repeats |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for arm, s in res["summary"].items():
        lines.append(f"| {arm} | {s['runs']} | {s['failed_runs']} | {_f(s['correct'], 1)} | {_f(s['top3'], 1)} | "
                     f"{_f(s['grounded'], 1)} | {_f(s['evidence_precision'], 1)} | {_f(s['evidence_coverage'], 1)} | "
                     f"{_f(s['unsupported_claim_rate'], 1)} | {_f(s['median_wall_s'])} | {_f(s['median_prompt_tokens'])} | "
                     f"{_f(s['median_output_tokens'])} | {_f(s['median_cpu_s'])} | {_f(s['max_peak_rss_mb'])} | "
                     f"{_f(s['median_evidence_tokens'])} | {_f(s['median_repeated_exposures'])} |")
    def row(name, v):
        if not v.get("n_cases"):
            return f"| {name} | 0 | – | – | – | – | – |"
        mc = v.get("mcnemar", {})
        return (f"| {name} | {v['n_cases']} ({v['n_families']} fam.) | {_f(v['mean_a'])} vs {_f(v['mean_b'])} | "
                f"{v['effect']:+.3f} | [{v['ci95'][0]:+.3f}, {v['ci95'][1]:+.3f}] | {v['perm_p']:.3f}"
                f"{' (Holm ' + format(v['perm_p_holm'], '.3f') + ')' if 'perm_p_holm' in v else ''} | "
                f"{(str(mc.get('a_only')) + '/' + str(mc.get('b_only')) + ', p=' + format(mc['p'], '.3f')) if mc else '–'} |")
    lines += ["", "| Comparison (A − B) | Cases | Means | Effect | 95% CI | Perm. p | McNemar (A only/B only) |",
              "|---|---|---|---|---|---|---|", row("PRIMARY correct: E3 − E2b", res["primary"])]
    lines += [row(f"secondary {k}", v) for k, v in res["secondary"].items()]
    lines += ["", "| Stratum (E3 − E2b, correct) | Cases | Means | Effect | 95% CI | Perm. p | McNemar |",
              "|---|---|---|---|---|---|---|"] + [row(s, v) for s, v in res["primary_by_stratum"].items()]
    return "\n".join(lines) + "\n"
