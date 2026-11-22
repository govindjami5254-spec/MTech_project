"""Claim-level grounding validator (M9). Applied identically to every arm's raw report.

For each claim of each hypothesis:
1. cited IDs must exist in this run's evidence ledger (else: fabricated, removed);
2. evidence flagged as suspected prompt injection never supports a claim;
3. the claim must share at least ``min_overlap`` content words with its remaining cited evidence
   (component name + message; exact or >= 5-character shared prefix), otherwise it is removed.
A hypothesis survives only if its cause component is a known component and at least one supported
claim cites evidence from, or naming, that component. If no hypothesis survives, the validated report
abstains. The raw report is kept unchanged, so A3 (validator off) is scored from it.

This is a deliberately simple, deterministic lexical check; its precision must be checked against
manual labels (see threats to validity).
"""
from __future__ import annotations

import re

from .evidence import EvidenceLedger
from .schemas import Claim, FinalReport, Hypothesis, ValidationStats

_STOP = set("""the and for that with from this was were are has have had not but into then than its their
there about after before while which when what who how why been being also over under due because
root cause caused causes causing symptom symptoms downstream upstream service services component
error errors failed failure failures failing issue issues event events log logs logged indicating
indicates shows showed led leading resulted result results evidence line lines reported reports""".split())
_WORD = re.compile(r"[a-z0-9][a-z0-9_.-]*[a-z0-9]|[a-z0-9]")
NO_SURVIVOR_GAP = "No hypothesis passed evidence-grounding validation."


def content_words(text: str) -> set[str]:
    words = set()
    for w in _WORD.findall(text.lower()):
        words.add(w)
        words.update(p for p in re.split(r"[._/:-]", w) if p != w)      # also the parts of compounds
    return {w for w in words if len(w) >= 3 and w not in _STOP}


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _match(word: str, pool: set[str]) -> bool:
    """Exact match, or both words >= 5 characters sharing a >= 5-character prefix (write/writes)."""
    if word in pool:
        return True
    return len(word) >= 5 and any(len(p) >= 5 and _common_prefix(word, p) >= 5 for p in pool)


def support_overlap(claim: str, evidence_text: str) -> int:
    pool = content_words(evidence_text)
    return sum(1 for w in content_words(claim) if _match(w, pool))


def validate_report(report: FinalReport, ledger: EvidenceLedger, known_components: list[str],
                    min_overlap: int = 2) -> tuple[FinalReport, ValidationStats]:
    known = set(known_components)
    by_id = {e.id: e for e in ledger.items()}
    total = supported = fabricated = suspicious = dropped = 0
    kept: list[Hypothesis] = []
    for hyp in report.hypotheses:
        good_claims, grounded = [], False
        for claim in hyp.claims:
            total += 1
            ids = list(dict.fromkeys(claim.evidence_ids))
            valid = [i for i in ids if i in by_id]
            fabricated += len(ids) - len(valid)
            clean = [i for i in valid if not by_id[i].suspicious]
            suspicious += len(valid) - len(clean)
            words = content_words(claim.text)
            ev_text = " ".join(f"{by_id[i].component} {by_id[i].message}" for i in clean)
            overlap = support_overlap(claim.text, ev_text) if clean else 0
            ok = bool(clean) and bool(words) and overlap >= min(min_overlap, len(words))
            if ok:
                supported += 1
                good_claims.append(Claim(text=claim.text, evidence_ids=clean))
                comp = hyp.cause_component
                if any(by_id[i].component == comp or comp in by_id[i].message for i in clean):
                    grounded = True
        if hyp.cause_component in known and good_claims and grounded:
            kept.append(Hypothesis(cause_component=hyp.cause_component, cause_summary=hyp.cause_summary,
                                   confidence=hyp.confidence, claims=good_claims))
        else:
            dropped += 1
    abstain_by_validator = not report.abstained and not kept
    gaps = list(report.evidence_gaps)
    if abstain_by_validator:
        gaps = (gaps[:1] + [NO_SURVIVOR_GAP])[:2]
    validated = FinalReport(insufficient_evidence=report.insufficient_evidence or not kept,
                            hypotheses=kept, evidence_gaps=gaps, recommendations=list(report.recommendations))
    stats = ValidationStats(claims_total=total, claims_supported=supported, fabricated_ids=fabricated,
                            suspicious_citations=suspicious, hypotheses_in=len(report.hypotheses),
                            hypotheses_dropped=dropped, abstained_by_validator=abstain_by_validator)
    return validated, stats
