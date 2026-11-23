"""Exploratory statistics (M10). Case = unit; families = clusters (D-020, D-024).

* Per-case score: mean over repeated runs of a metric.
* Effect: mean over cases of the paired per-case difference (arm A - arm B).
* Permutation p-value: two-sided sign-flip at FAMILY level (exact for <= 20 families).
* 95% CI: cluster bootstrap (resample families, then cases within families).
* Sensitivity: exact McNemar on per-case majority outcomes.
These are descriptive for an underpowered exploratory design; no significance claim is made.
"""
from __future__ import annotations

import itertools
from collections import defaultdict
from typing import Optional

import numpy as np
from scipy.stats import binomtest


def per_case(rows: list[dict], metric: str) -> dict[tuple[str, str], tuple[float, str, str]]:
    """(arm, case) -> (mean metric over runs, family, stratum); rows with metric None are skipped."""
    acc: dict = defaultdict(list)
    meta = {}
    for r in rows:
        if r.get(metric) is None:
            continue
        acc[(r["arm"], r["case_id"])].append(float(r[metric]))
        meta[r["case_id"]] = (r["family_id"], r["stratum"])
    return {k: (float(np.mean(v)), *meta[k[1]]) for k, v in acc.items()}


def paired(rows: list[dict], metric: str, a: str, b: str, n_boot: int = 10_000, seed: int = 7,
           stratum: Optional[str] = None) -> dict:
    pc = per_case(rows, metric)
    cases = sorted({c for (arm, c) in pc if arm == a} & {c for (arm, c) in pc if arm == b})
    if stratum:
        cases = [c for c in cases if pc[(a, c)][2] == stratum]
    if not cases:
        return {"metric": metric, "a": a, "b": b, "n_cases": 0}
    diff = np.array([pc[(a, c)][0] - pc[(b, c)][0] for c in cases])
    fam = [pc[(a, c)][1] for c in cases]
    fams = sorted(set(fam))
    sums = np.array([diff[[f == x for f in fam]].sum() for x in fams])
    n = len(cases)
    obs = diff.mean()
    if len(fams) <= 20:
        signs = np.array(list(itertools.product([1, -1], repeat=len(fams))))
    else:
        signs = np.random.default_rng(seed).choice([1, -1], size=(100_000, len(fams)))
    null = (signs * sums).sum(axis=1) / n
    p = float((np.abs(null) >= abs(obs) - 1e-12).mean())
    rng = np.random.default_rng(seed)
    idx_by_fam = {x: np.where(np.array(fam) == x)[0] for x in fams}
    boots = np.empty(n_boot)
    for i in range(n_boot):
        picked = rng.choice(fams, size=len(fams), replace=True)
        sample = np.concatenate([rng.choice(idx_by_fam[x], size=len(idx_by_fam[x]), replace=True) for x in picked])
        boots[i] = diff[sample].mean()
    lo, hi = np.percentile(boots, [2.5, 97.5])
    out = {"metric": metric, "a": a, "b": b, "n_cases": n, "n_families": len(fams),
           "mean_a": float(np.mean([pc[(a, c)][0] for c in cases])),
           "mean_b": float(np.mean([pc[(b, c)][0] for c in cases])),
           "effect": float(obs), "ci95": [float(lo), float(hi)], "perm_p": p, "icc": _icc(diff, fam)}
    if metric in ("correct", "top1", "top3"):
        maj_a = {c: pc[(a, c)][0] >= 0.5 for c in cases}
        maj_b = {c: pc[(b, c)][0] >= 0.5 for c in cases}
        b_ = sum(maj_a[c] and not maj_b[c] for c in cases)
        c_ = sum(maj_b[c] and not maj_a[c] for c in cases)
        out["mcnemar"] = {"a_only": b_, "b_only": c_,
                          "p": float(binomtest(b_, b_ + c_, 0.5).pvalue) if b_ + c_ else 1.0}
    return out


def _icc(values: np.ndarray, groups: list[str]) -> Optional[float]:
    """One-way ANOVA ICC(1) of per-case differences within families (descriptive)."""
    labels = sorted(set(groups))
    k = len(values) / len(labels)
    if len(labels) < 2 or k <= 1:
        return None
    means = {g: values[[x == g for x in groups]].mean() for g in labels}
    grand = values.mean()
    msb = sum(len(values[[x == g for x in groups]]) * (means[g] - grand) ** 2 for g in labels) / (len(labels) - 1)
    msw = sum(((values[[x == g for x in groups]] - means[g]) ** 2).sum() for g in labels) / (len(values) - len(labels))
    denom = msb + (k - 1) * msw
    return float((msb - msw) / denom) if denom > 0 else None


def holm(pvalues: dict[str, float]) -> dict[str, float]:
    items = sorted(pvalues.items(), key=lambda kv: kv[1])
    m, out, running = len(items), {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def arm_summary(rows: list[dict]) -> dict:
    by_arm: dict = defaultdict(list)
    for r in rows:
        by_arm[r["arm"]].append(r)
    out = {}
    for arm, rs in sorted(by_arm.items()):
        def mean(key):
            v = [r[key] for r in rs if r.get(key) is not None]
            return float(np.mean(v)) if v else None

        def median(key):
            v = [r[key] for r in rs if r.get(key) is not None]
            return float(np.median(v)) if v else None
        out[arm] = {"runs": len(rs), "failed_runs": sum(r["status"] != "ok" for r in rs),
                    "correct": mean("correct"), "top1": mean("top1"), "top3": mean("top3"),
                    "grounded": mean("grounded"), "evidence_precision": mean("evidence_precision"),
                    "evidence_coverage": mean("evidence_coverage"),
                    "unsupported_claim_rate": mean("unsupported_claim_rate"),
                    "median_wall_s": median("wall_seconds"), "median_prompt_tokens": median("prompt_tokens"),
                    "median_output_tokens": median("output_tokens"), "median_cpu_s": median("cpu_seconds"),
                    "max_peak_rss_mb": max((r["peak_rss_mb"] for r in rs if r.get("peak_rss_mb")), default=None),
                    "max_peak_uss_mb": max((r["peak_uss_mb"] for r in rs if r.get("peak_uss_mb")), default=None),
                    "max_peak_pss_mb": max((r["peak_pss_mb"] for r in rs if r.get("peak_pss_mb")), default=None),
                    "max_host_used_mb": max((r["host_used_peak_mb"] for r in rs if r.get("host_used_peak_mb")), default=None),
                    "normalised_fields_total": sum(r.get("normalised_fields") or 0 for r in rs),
                    "runs_with_truncation": sum(1 for r in rs if (r.get("normalised_fields") or 0) > 0),
                    "median_evidence_tokens": median("unique_evidence_tokens"),
                    "median_repeated_exposures": median("repeated_exposures"),
                    "median_tool_calls": median("tool_calls"), "median_llm_calls": median("llm_calls"),
                    "by_stratum": {s: float(np.mean([r["correct"] for r in rs if r["stratum"] == s]))
                                   for s in sorted({r["stratum"] for r in rs})}}
    return out
