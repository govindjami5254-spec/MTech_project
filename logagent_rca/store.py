"""Investigation store (application layer): file-based persistence shared by CLI and web.

It extends the existing research layout instead of introducing a database:

    <workspace>/
      cases/<investigation_id>/incident.json + <uploaded logs>     agent-visible case bundle (unchanged format)
      investigations/<investigation_id>/
          meta.json          investigation metadata, analyses and their status (this module)
          events.jsonl       application-level progress events (this module)
          runs/ audit/ transcripts/ index.jsonl                      written by the existing runner.run_one
      no-truth/                                                     empty; satisfies the config's truth-directory rule
      .analysis.lock                                                serialises model use across CLI and web

Run records remain the existing ``RunRecord`` JSON files, so every existing reader (and ``analyze``) can open them.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Iterator, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .ingest import resolve_inside
from .schemas import Incident, RunRecord

InvestigationId = Annotated[str, StringConstraints(pattern=r"^inv-[0-9]{8}-[0-9a-f]{8}$")]
Mode = Literal["E2b", "E3"]
AnalysisStatus = Literal["queued", "running", "ok", "failed", "aborted", "error"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FileInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    bytes: int
    lines: int
    sha256: str


class Analysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    mode: Mode
    repeat: int
    status: AnalysisStatus = "queued"
    requested_at: datetime
    requested_by: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None


class Investigation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1"
    id: InvestigationId
    created_at: datetime
    owner: str
    incident: Incident
    log_files: list[FileInfo]
    ingest_stats: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    analyses: list[Analysis] = Field(default_factory=list)

    @property
    def status(self) -> str:
        if not self.analyses:
            return "created"
        return self.analyses[-1].status


class _FileLock:
    """Advisory exclusive lock on a file (fcntl on POSIX, msvcrt on Windows)."""

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+b")
        if os.name == "nt":                                   # pragma: no cover - Windows
            import msvcrt
            self._fh.seek(0)
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        if os.name == "nt":                                   # pragma: no cover - Windows
            import msvcrt
            self._fh.seek(0)
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        self._fh.close()
        return False


class InvestigationStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.cases = self.root / "cases"
        self.investigations = self.root / "investigations"
        self.no_truth = self.root / "no-truth"
        for d in (self.cases, self.investigations, self.no_truth):
            d.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ ids and paths
    @staticmethod
    def new_id() -> str:
        return f"inv-{utcnow().strftime('%Y%m%d')}-{secrets.token_hex(4)}"

    def _check(self, inv_id: str) -> str:
        if not re.fullmatch(r"inv-[0-9]{8}-[0-9a-f]{8}", inv_id or ""):
            raise KeyError(f"invalid investigation id: {inv_id!r}")
        return inv_id

    def case_dir(self, inv_id: str) -> Path:
        return resolve_inside(self.cases, self._check(inv_id))

    def inv_dir(self, inv_id: str) -> Path:
        return resolve_inside(self.investigations, self._check(inv_id))

    def analysis_lock(self) -> _FileLock:
        return _FileLock(self.root / ".analysis.lock")

    @contextlib.contextmanager
    def _meta_lock(self, inv_id: str) -> Iterator[None]:
        with self._lock, _FileLock(self.inv_dir(inv_id) / ".meta.lock"):
            yield

    # ------------------------------------------------------------------ metadata
    def save(self, inv: Investigation) -> None:
        d = self.inv_dir(inv.id)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "meta.json.tmp"
        tmp.write_text(inv.model_dump_json(indent=1), encoding="utf-8")
        tmp.replace(d / "meta.json")

    def load(self, inv_id: str) -> Investigation:
        path = self.inv_dir(inv_id) / "meta.json"
        if not path.is_file():
            raise KeyError(f"unknown investigation: {inv_id}")
        return Investigation.model_validate_json(path.read_text(encoding="utf-8"))

    def update(self, inv_id: str, fn) -> Investigation:
        """Read-modify-write of meta.json under a per-investigation lock."""
        with self._meta_lock(inv_id):
            inv = self.load(inv_id)
            fn(inv)
            self.save(inv)
            return inv

    def list(self) -> list[Investigation]:
        out = []
        for p in sorted(self.investigations.iterdir(), reverse=True):
            if (p / "meta.json").is_file():
                try:
                    out.append(self.load(p.name))
                except (KeyError, ValueError):
                    continue
        return out

    # ------------------------------------------------------------------ events
    def add_event(self, inv_id: str, kind: str, run_id: Optional[str] = None, **fields) -> None:
        entry = {"ts": utcnow().isoformat(), "kind": kind, "run_id": run_id, **fields}
        with self._lock, (self.inv_dir(inv_id) / "events.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")

    def events(self, inv_id: str, run_id: Optional[str] = None) -> list[dict]:
        path = self.inv_dir(inv_id) / "events.jsonl"
        if not path.is_file():
            return []
        rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        return [r for r in rows if run_id is None or r.get("run_id") in (None, run_id)]

    def audit_events(self, inv_id: str, run_id: str) -> list[dict]:
        path = resolve_inside(self.inv_dir(inv_id) / "audit", f"{run_id}.jsonl")
        if not path.is_file():
            return []
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    # ------------------------------------------------------------------ run records
    def record_path(self, inv_id: str, run_id: str) -> Path:
        return resolve_inside(self.inv_dir(inv_id) / "runs", f"{run_id}.json")

    def load_record(self, inv_id: str, run_id: str) -> RunRecord:
        path = self.record_path(inv_id, run_id)
        if not path.is_file():
            raise KeyError(f"no run record {run_id}")
        return RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
