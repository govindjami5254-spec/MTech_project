"""Shared final-answer call: same instruction, same JSON schema, one retry on invalid output (M5)."""
from __future__ import annotations

import json

from pydantic import ValidationError

from .context import LLMUsage
from .llm import LLMError
from .prompts import FINAL_INSTRUCTION, FINAL_SCHEMA
from .schemas import FinalReport

# Schema limits mirrored here: Ollama's grammar does not enforce string or list lengths, so an
# otherwise valid answer is normalised (truncated) identically for every arm instead of forcing a
# multi-minute CPU retry. Each normalisation is counted.
_LIMITS = {"text": 160, "hyp": 3, "claims": 3, "ids": 4, "lists": 2}


def _cut(text, n):
    text = str(text).strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def normalise(data: dict) -> tuple[dict, int]:
    """Truncate over-long fields to the schema limits. Returns (data, number of edits)."""
    edits = 0
    if not isinstance(data, dict):
        return data, 0
    hyps = data.get("hypotheses")
    if isinstance(hyps, list):
        if len(hyps) > _LIMITS["hyp"]:
            data["hypotheses"], edits = hyps[: _LIMITS["hyp"]], edits + 1
        for h in data["hypotheses"]:
            if not isinstance(h, dict):
                continue
            if isinstance(h.get("cause_summary"), str) and len(h["cause_summary"]) > _LIMITS["text"]:
                h["cause_summary"], edits = _cut(h["cause_summary"], _LIMITS["text"]), edits + 1
            if isinstance(h.get("confidence"), (int, float)) and not 0 <= h["confidence"] <= 1:
                h["confidence"], edits = min(1.0, max(0.0, float(h["confidence"]))), edits + 1
            claims = h.get("claims")
            if isinstance(claims, list):
                if len(claims) > _LIMITS["claims"]:
                    h["claims"], edits = claims[: _LIMITS["claims"]], edits + 1
                for c in h["claims"]:
                    if isinstance(c, dict):
                        if isinstance(c.get("text"), str) and len(c["text"]) > _LIMITS["text"]:
                            c["text"], edits = _cut(c["text"], _LIMITS["text"]), edits + 1
                        if isinstance(c.get("evidence_ids"), list) and len(c["evidence_ids"]) > _LIMITS["ids"]:
                            c["evidence_ids"], edits = c["evidence_ids"][: _LIMITS["ids"]], edits + 1
    for key in ("evidence_gaps", "recommendations"):
        lst = data.get(key)
        if isinstance(lst, list):
            if len(lst) > _LIMITS["lists"]:
                data[key], edits = lst[: _LIMITS["lists"]], edits + 1
            data[key] = [_cut(x, _LIMITS["text"]) if isinstance(x, str) and len(x) > _LIMITS["text"] else x
                         for x in data[key]]
    return data, edits


def request_final(llm, messages: list, seed: int, usage: LLMUsage, max_retries: int):
    """Append the final instruction to ``messages`` and parse a FinalReport.

    Returns (report or None, error or None). ``messages`` is extended in place.
    """
    messages.append({"role": "user", "content": FINAL_INSTRUCTION})
    error = None
    for attempt in range(max_retries + 1):
        try:
            resp = llm.chat(messages, seed=seed + attempt, schema=FINAL_SCHEMA)
        except LLMError as exc:
            error = str(exc)
            usage.parse_failures += 1
            continue
        usage.calls += 1
        usage.prompt_tokens += resp.prompt_tokens
        usage.output_tokens += resp.output_tokens
        usage.seconds += resp.seconds
        try:
            data, edits = normalise(json.loads(resp.content))
            usage.normalised_fields += edits
            return FinalReport.model_validate(data), None
        except (ValidationError, json.JSONDecodeError, ValueError, TypeError) as exc:
            usage.parse_failures += 1
            error = f"invalid final report: {str(exc)[:300]}"
            messages.append({"role": "assistant", "content": resp.content[:2000]})
            messages.append({"role": "user", "content": "Your answer did not match the schema "
                             f"({str(exc)[:200]}). Reply again with valid JSON only."})
    return None, error
