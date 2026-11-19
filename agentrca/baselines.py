"""Comparison arms. All LLM arms share the same final prompt/schema/validator as the agent;
only the evidence they receive (and whether they may iterate) differs.

  rule      B1  rule-only: static diagnosis attached to the matching detection rule
  heuristic B1b no-LLM temporal heuristic: component with the earliest WARN+ event in the window
  single    B2  single-pass LLM given the tail of the log before the incident
  static    B3  single-pass LLM given deterministic retrieval with the same evidence budget
                as the agent (isolates the benefit of *iteration*, not of retrieval)
"""
from __future__ import annotations

import time
from datetime import timedelta

from .agent import Investigation, RunMetrics, generate_hypotheses
from .config import Config
from .evidence import EvidenceStore
from .ingest import LogIndex
from .models import Incident
from .safety import AuditLog


def _inv(incident, store, raw, gaps, metrics, t0) -> Investigation:
    metrics.wall_seconds = time.monotonic() - t0
    return Investigation(incident, store, raw, gaps, metrics)


def run_rule(cfg: Config, index: LogIndex, incident: Incident, llm, audit: AuditLog) -> Investigation:
    t0 = time.monotonic()
    store = EvidenceStore(cfg.safety.quarantine_suspicious)
    ev = store.add([incident.trigger], 0, "incident")[0]
    raw = {"hypotheses": [{
        "cause_component": incident.trigger.component,
        "cause_summary": incident.diagnosis_hint or incident.description,
        "confidence": 0.5,
        "claims": [{"text": incident.trigger.message, "evidence_ids": [ev.id]}]}],
        "evidence_gaps": ["Rule-based detection only; no dependency analysis."],
        "recommendations": []}
    return _inv(incident, store, raw, [], RunMetrics(), t0)


def run_heuristic(cfg: Config, index: LogIndex, incident: Incident, llm, audit: AuditLog) -> Investigation:
    t0 = time.monotonic()
    store = EvidenceStore(cfg.safety.quarantine_suspicious)
    store.add([incident.trigger], 0, "incident")
    start = incident.ts - timedelta(seconds=cfg.agent.lookback_s)
    probs = index.problem_events(start, incident.ts, "WARN")
    hyps = []
    for comp, evs in sorted(probs.items(), key=lambda kv: kv[1][0].ts)[:3]:
        added = store.add(evs[:2], 0, "heuristic")
        hyps.append({"cause_component": comp, "cause_summary": f"{comp} was the first component to log problems",
                     "confidence": 0.5,
                     "claims": [{"text": evs[0].message, "evidence_ids": [added[0].id]}]})
    raw = {"hypotheses": hyps, "evidence_gaps": ["Temporal heuristic only; no causal validation."],
           "recommendations": []}
    return _inv(incident, store, raw, [], RunMetrics(), t0)


def run_single(cfg: Config, index: LogIndex, incident: Incident, llm, audit: AuditLog) -> Investigation:
    t0 = time.monotonic()
    metrics, store = RunMetrics(), EvidenceStore(cfg.safety.quarantine_suspicious)
    before = [e for e in index.events if e.ts <= incident.ts]
    tail = before[-cfg.agent.single_tail_events:]
    store.add([incident.trigger], 0, "incident")
    store.add(tail, 0, "tail")
    raw = generate_hypotheses(llm, cfg, incident, store.select(cfg.agent.max_final_evidence),
                              [], metrics, audit, phase="single")
    metrics.model_memory_bytes = getattr(llm, "model_memory_bytes", lambda: None)()
    return _inv(incident, store, raw, [], metrics, t0)


def run_static(cfg: Config, index: LogIndex, incident: Incident, llm, audit: AuditLog) -> Investigation:
    t0 = time.monotonic()
    metrics, store = RunMetrics(), EvidenceStore(cfg.safety.quarantine_suspicious)
    store.add([incident.trigger], 0, "incident")
    start = incident.ts - timedelta(seconds=cfg.agent.lookback_s)
    probs = index.problem_events(start, incident.ts, "WARN")
    for comp, evs in sorted(probs.items(), key=lambda kv: kv[1][0].ts):
        store.add(evs[: cfg.agent.static_per_component], 0, "static_retrieval")
    raw = generate_hypotheses(llm, cfg, incident, store.select(cfg.agent.max_final_evidence),
                              [], metrics, audit, phase="static")
    metrics.model_memory_bytes = getattr(llm, "model_memory_bytes", lambda: None)()
    return _inv(incident, store, raw, [], metrics, t0)
