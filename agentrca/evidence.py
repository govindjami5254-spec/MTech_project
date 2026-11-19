"""Evidence store: every finding is linked to source, timestamp, tool and step."""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Iterable, Optional

from .ingest import event_line, fmt_ts
from .models import LogEvent, sev_rank


@dataclass
class Evidence:
    id: str
    uid: str
    ts: str
    severity: str
    component: str
    source: str
    line_no: int
    message: str
    step: int
    tool: str
    suspicious: bool = False

    def line(self) -> str:
        return f"[{self.id}] {self.ts} {self.severity} {self.component}: {self.message}"

    def to_dict(self) -> dict:
        return asdict(self)


class EvidenceStore:
    def __init__(self, quarantine: bool = False) -> None:
        self.quarantine = quarantine
        self._items: dict[str, Evidence] = {}
        self._by_uid: dict[str, str] = {}

    def add(self, events: Iterable[LogEvent], step: int, tool: str) -> list[Evidence]:
        out = []
        for e in events:
            eid = self._by_uid.get(e.uid)
            if eid is None:
                eid = f"E{len(self._items) + 1}"
                msg = ("[line quarantined: suspected prompt-injection content]"
                       if self.quarantine and e.suspicious else e.message)
                self._by_uid[e.uid] = eid
                self._items[eid] = Evidence(
                    id=eid, uid=e.uid, ts=fmt_ts(e.ts), severity=e.severity,
                    component=e.component, source=e.source, line_no=e.line_no,
                    message=msg, step=step, tool=tool, suspicious=e.suspicious)
            out.append(self._items[eid])
        return out

    def get(self, eid: str) -> Optional[Evidence]:
        return self._items.get(eid)

    def has(self, eid: str) -> bool:
        return eid in self._items

    def all(self) -> list[Evidence]:
        return list(self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    def select(self, limit: int) -> list[Evidence]:
        """Pick up to `limit` items for the final prompt: severe first, shown chronologically."""
        items = self.all()
        if len(items) <= limit:
            chosen = items
        else:
            chosen = sorted(items, key=lambda x: (-sev_rank(x.severity), int(x.id[1:])))[:limit]
        return sorted(chosen, key=lambda x: (x.ts, x.source, x.line_no))


_ID_RE = re.compile(r"(\d+)")


def normalize_id(raw) -> Optional[str]:
    m = _ID_RE.search(str(raw))
    return f"E{int(m.group(1))}" if m else None
