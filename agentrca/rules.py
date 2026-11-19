"""Deterministic, configurable incident detection."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Optional

import yaml

from .ingest import LogIndex
from .models import Incident, norm_severity, sev_rank


@dataclass
class Rule:
    id: str
    description: str = ""
    priority: int = 5
    component: Optional[str] = None
    severity: list = field(default_factory=lambda: ["ERROR", "FATAL"])
    contains: list = field(default_factory=list)       # any-of, case-insensitive
    window_s: int = 120                                # events within this window = one incident
    diagnosis: Optional[str] = None                    # static text used by the rule-only baseline


def load_rules(path: str) -> list[Rule]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    rules = []
    for r in data.get("rules", []):
        rules.append(Rule(
            id=r["id"], description=r.get("description", ""), priority=int(r.get("priority", 5)),
            component=r.get("component"), severity=[norm_severity(s) for s in r.get("severity", ["ERROR", "FATAL"])],
            contains=[str(c).lower() for c in r.get("contains", [])],
            window_s=int(r.get("window_s", 120)), diagnosis=r.get("diagnosis")))
    return rules


def detect(index: LogIndex, rules: list[Rule]) -> list[Incident]:
    incidents: list[Incident] = []
    for rule in rules:
        last_ts = None
        for e in index.events:
            if rule.component and e.component != rule.component:
                continue
            if norm_severity(e.severity) not in rule.severity:
                continue
            if rule.contains and not any(c in e.message.lower() for c in rule.contains):
                continue
            if last_ts is not None and e.ts - last_ts <= timedelta(seconds=rule.window_s):
                continue
            last_ts = e.ts
            incidents.append(Incident(
                id="", rule_id=rule.id, description=rule.description or rule.id,
                priority=rule.priority, trigger=e, ts=e.ts, diagnosis_hint=rule.diagnosis))
    incidents.sort(key=lambda i: (i.priority, i.ts))
    for n, inc in enumerate(incidents, 1):
        inc.id = f"INC-{n:03d}"
    return incidents
