"""RCA report rendering shared by CLI and web: RunRecord -> view model / Markdown.

Pure functions; nothing here calls the model or changes a record. Every evidence reference is resolved to the
evidence item stored in the run record (source file, line number, timestamp, message as presented to the model).
"""
from __future__ import annotations

from typing import Optional

from .schemas import CaseManifest, FinalReport, RunRecord

CONFIDENCE_NOTE = ("Confidence is the model's own self-assessed score between 0 and 1. It is not a calibrated "
                   "probability and has not been validated against outcomes.")
RECOMMENDATION_NOTE = ("Recommendations are advisory, read-only suggestions for a human operator. LogAgent-RCA "
                       "never executes them; their quality is not evaluated.")


def _claims(report: Optional[FinalReport]) -> set[tuple]:
    if report is None:
        return set()
    return {(h.cause_component, c.text) for h in report.hypotheses for c in h.claims}


def build_view(rec: RunRecord, manifest: Optional[CaseManifest] = None) -> dict:
    ev = {e.id: e for e in rec.evidence}
    rep = rec.report_validated

    def evidence(ids):
        return [{"id": i, "source": ev[i].source, "line_no": ev[i].line_no,
                 "ts": ev[i].ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "severity": ev[i].severity.value,
                 "component": ev[i].component, "message": ev[i].message, "suspicious": ev[i].suspicious}
                for i in ids if i in ev]

    hyps = []
    for rank, h in enumerate(rep.hypotheses if rep else [], 1):
        hyps.append({"rank": rank, "cause_component": h.cause_component, "cause_summary": h.cause_summary,
                     "confidence": h.confidence,
                     "claims": [{"text": c.text, "evidence": evidence(c.evidence_ids)} for c in h.claims]})
    kept = _claims(rep)
    removed = []
    if rec.report_raw:
        for h in rec.report_raw.hypotheses:
            for c in h.claims:
                if (h.cause_component, c.text) not in kept:
                    removed.append({"cause_component": h.cause_component, "text": c.text,
                                    "evidence_ids": list(c.evidence_ids),
                                    "unknown_ids": [i for i in c.evidence_ids if i not in ev]})
    m = rec.metrics
    return {
        "run_id": rec.run_id, "case_id": rec.case_id, "mode": rec.arm.value, "repeat": rec.repeat,
        "status": rec.status.value, "error": rec.error, "started_at": rec.started_at.isoformat(),
        "incident": manifest.incident.model_dump(mode="json") if manifest else None,
        "abstained": rep.abstained if rep else None,
        "hypotheses": hyps,
        "evidence_gaps": list(rep.evidence_gaps) if rep else [],
        "recommendations": list(rep.recommendations) if rep else [],
        "validation": (rec.validation.model_dump() | {"unsupported_claim_rate": rec.validation.unsupported_claim_rate})
        if rec.validation else None,
        "removed_claims": removed,
        "evidence": evidence([e.id for e in rec.evidence]),
        "tool_calls": [t.model_dump(mode="json") for t in rec.tool_calls],
        "metrics": m.model_dump(mode="json"),
        "model": rec.model.model_dump(mode="json") if rec.model else None,
        "config_hash": rec.config_hash, "code_commit": rec.code_commit,
        "notes": {"confidence": CONFIDENCE_NOTE, "recommendations": RECOMMENDATION_NOTE},
    }


def to_markdown(rec: RunRecord, manifest: Optional[CaseManifest] = None) -> str:
    v = build_view(rec, manifest)
    inc = v["incident"] or {}
    L = [f"# RCA report — {inc.get('id', v['case_id'])} ({v['mode']}, run {v['run_id']})", "",
         f"- Investigation: `{v['case_id']}`; status: **{v['status']}**" + (f"; error: {v['error']}" if v["error"] else ""),
         f"- Incident: {inc.get('description', '–')} at {inc.get('ts', '–')}; trigger `{inc.get('trigger_uid', '–')}`"
         f" ({inc.get('trigger_component', '–')})",
         f"- Model: {(v['model'] or {}).get('name', '–')} (weights {((v['model'] or {}).get('weights_digest') or '–')[:12]}…), "
         f"temperature {(v['model'] or {}).get('temperature', '–')}, seed {(v['model'] or {}).get('seed', '–')}",
         f"- Code commit `{(v['code_commit'] or '–')[:12]}`, config hash `{v['config_hash'][:12]}`", "",
         "## Ranked root-cause hypotheses", ""]
    if v["abstained"]:
        L.append("_The report states that the evidence is insufficient to identify a root cause._")
    for h in v["hypotheses"]:
        L += [f"### {h['rank']}. {h['cause_component']} — confidence {h['confidence']:.2f}", "", h["cause_summary"], ""]
        for c in h["claims"]:
            L.append(f"- {c['text']}")
            for e in c["evidence"]:
                L.append(f"  - [{e['id']}] `{e['source']}:{e['line_no']}` {e['ts']} {e['severity']} "
                         f"{e['component']}: {e['message']}")
        L.append("")
    L += [f"> {CONFIDENCE_NOTE}", "", "## Evidence gaps"] + ([f"- {g}" for g in v["evidence_gaps"]] or ["- none stated"])
    L += ["", "## Recommendations"] + ([f"- {r}" for r in v["recommendations"]] or ["- none"]) + ["", f"> {RECOMMENDATION_NOTE}"]
    L += ["", "## Grounding validation"]
    if v["validation"]:
        s = v["validation"]
        L += [f"- Claims supported: {s['claims_supported']} of {s['claims_total']} "
              f"(unsupported rate {s['unsupported_claim_rate']:.2f})",
              f"- Fabricated evidence IDs: {s['fabricated_ids']}; injection-flagged citations: {s['suspicious_citations']}",
              f"- Hypotheses dropped: {s['hypotheses_dropped']} of {s['hypotheses_in']}"
              + ("; the validator turned the report into an abstention" if s["abstained_by_validator"] else "")]
    else:
        L.append("- No model report was produced, so nothing was validated.")
    if v["removed_claims"]:
        L += ["", "Claims removed by the validator:"] + [f"- ({r['cause_component']}) {r['text']} — cited "
                                                         f"{', '.join(r['evidence_ids']) or 'nothing'}" for r in v["removed_claims"]]
    m = v["metrics"]
    L += ["", "## Runtime and tokens",
          f"- Wall time {m['wall_seconds']:.0f} s; LLM time {m['llm_seconds']:.0f} s; LLM calls {m['llm_calls']}; "
          f"steps {m['steps']}; tool calls {m['tool_calls']} (refused {m['blocked_tool_calls']}); gate rounds {m['gate_rounds']}",
          f"- Evidence budget: {m['unique_evidence_tokens']} of {m['evidence_token_budget']} tokens, "
          f"{m['unique_evidence_items']} items, {m['repeated_exposures']} repeated exposures",
          f"- Processed prompt tokens {m['prompt_tokens_total']}; output tokens {m['output_tokens_total']}; "
          f"invalid-output retries {m['parse_failures']}; truncated fields {m['normalised_fields']}",
          "", "## All evidence presented to the model", "",
          "| ID | Source | Line | Time | Severity | Component | Message |", "|---|---|---|---|---|---|---|"]
    for e in v["evidence"]:
        msg = e["message"].replace("|", "\\|")
        L.append(f"| {e['id']} | {e['source']} | {e['line_no']} | {e['ts']} | {e['severity']} | {e['component']} | "
                 f"{msg}{' (flagged: possible prompt injection)' if e['suspicious'] else ''} |")
    return "\n".join(L) + "\n"
