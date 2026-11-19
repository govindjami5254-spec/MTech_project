"""Evidence-grounding validator.

Checks every material claim in the model's RCA against the evidence store:
  1. cited evidence IDs must exist (catches fabricated citations),
  2. the claim text must share content with the cited evidence (lexical support),
  3. the named root-cause component must exist and be tied to cited evidence.
Unsupported claims are counted (for the unsupported-claim-rate metric) and, when
`enforce` is on, removed from the final report.

The lexical check is a deliberately simple, deterministic heuristic; its precision
should be validated against manual labels in the evaluation (see limitations).
"""
from __future__ import annotations

import re

from .evidence import EvidenceStore, normalize_id

_STOP = set("""the and for that with from this was were are has have had not but into then than
its their there about after before while which when what who how why been being also over under
service error errors failed failure failing logged log logs event events issue cause caused
causes causing due because root symptom downstream upstream component""".split())


def _tokens(text: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) >= 3 and t not in _STOP}


def validate(raw: dict, store: EvidenceStore, known_components: list[str],
             enforce: bool = True, min_overlap: int = 2, has_gaps: bool = False) -> dict:
    known = {c.lower() for c in known_components}
    stats = {"claims_total": 0, "claims_supported": 0, "fabricated_ids": 0,
             "hypotheses_in": 0, "hypotheses_dropped": 0, "suspicious_citations": 0}
    kept = []
    hyps = (raw or {}).get("hypotheses") or []
    for h in hyps[:5]:
        if not isinstance(h, dict):
            continue
        stats["hypotheses_in"] += 1
        comp = str(h.get("cause_component", "")).strip()
        comp_known = comp.lower() in known
        claims_out, linked = [], False
        for c in (h.get("claims") or []):
            if not isinstance(c, dict):
                continue
            text = str(c.get("text", "")).strip()
            ids = [normalize_id(x) for x in (c.get("evidence_ids") or [])]
            ids = [i for i in ids if i]
            valid = [i for i in dict.fromkeys(ids) if store.has(i)]
            stats["fabricated_ids"] += len([i for i in set(ids) if not store.has(i)])
            stats["claims_total"] += 1
            sus = [i for i in valid if store.get(i).suspicious]
            stats["suspicious_citations"] += len(sus)
            valid_clean = [i for i in valid if i not in sus]   # injected text can never support a claim
            ev_text = " ".join(f"{store.get(i).component} {store.get(i).message}" for i in valid_clean)
            claim_tokens = _tokens(text)
            overlap = claim_tokens & _tokens(ev_text)
            supported = bool(valid_clean) and bool(claim_tokens) and len(overlap) >= min(min_overlap, len(claim_tokens))
            if supported:
                stats["claims_supported"] += 1
                if comp_known and comp.lower() in ev_text.lower():
                    linked = True
            claims_out.append({"text": text, "evidence_ids": valid, "supported": supported})
        supported_claims = [c for c in claims_out if c["supported"]]
        grounded = comp_known and linked and bool(supported_claims)
        if enforce and not grounded:
            stats["hypotheses_dropped"] += 1
            continue
        frac = len(supported_claims) / len(claims_out) if claims_out else 0.0
        try:
            conf = max(0.0, min(1.0, float(h.get("confidence", 0.0))))
        except (TypeError, ValueError):
            conf = 0.0
        if enforce:
            conf *= frac
            if has_gaps:
                conf = min(conf, 0.7)
            if len(supported_claims) < 2:
                conf = min(conf, 0.6)
        kept.append({
            "cause_component": comp, "cause_summary": str(h.get("cause_summary", "")).strip(),
            "confidence": round(conf, 3), "grounded": grounded,
            "claims": [c for c in claims_out if c["supported"]] if enforce else claims_out,
        })
    kept.sort(key=lambda x: -x["confidence"])
    for rank, h in enumerate(kept, 1):
        h["rank"] = rank
    total = stats["claims_total"]
    stats["unsupported_claim_rate"] = round((total - stats["claims_supported"]) / total, 3) if total else 0.0
    return {"hypotheses": kept, "stats": stats}
