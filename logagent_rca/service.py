"""Shared application services for real-incident diagnosis (used by the CLI and the web adapter).

The services prepare a case bundle from uploaded log files and incident details, then execute the existing
research engine unchanged: ``runner.run_one`` (same E2b/E3, tools, coverage gate, validator, prompts, Ollama
client, model settings and evidence budget). Nothing in this module implements diagnosis logic.

Experiment execution (``python -m logagent_rca run``) and real-incident diagnosis are kept separate: they use
different configurations (``configs/test.yaml`` vs ``configs/app.yaml``, identical model settings) and different
directories, and analyses refuse to start while the research experiment process is running (protects Ollama's
single slot and the experiment's latency measurements).
"""
from __future__ import annotations

import hashlib
import re
import shutil
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import psutil
from pydantic import ValidationError

from .config import Config, load_config
from .ingest import IngestError, PathViolation, load_case, parse_ts, resolve_inside, write_manifest
from .llm import LLMError, OllamaClient
from .runner import git_commit, run_one
from .schemas import ArmId, CaseManifest, Incident, RunRecord, Split
from .store import Analysis, FileInfo, Investigation, InvestigationStore, utcnow
from .tokens import counter_from_config

REPO_ROOT = Path(__file__).resolve().parent.parent
MODES = ("E2b", "E3")
SAFE_AUDIT_KINDS = {"e3_start", "tool_call", "tool_blocked", "coverage_gate", "coverage_gate_pending",
                    "coverage_gate_skipped", "controller_nudge", "injection_suspected", "e3_aborted", "e3_end",
                    "runner_retry"}


class ValidationProblem(ValueError):
    """User-correctable input problem; ``errors`` maps field name -> message."""

    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


class AnalysisRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class UploadLimits:
    max_files: int = 20
    max_file_bytes: int = 20_000_000
    max_total_bytes: int = 100_000_000
    max_lines: int = 200_000
    suffixes: tuple = (".log", ".txt")


_NAME_BAD = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(name: str, suffixes: tuple = (".log", ".txt")) -> str:
    """Basename only; safe characters; no hidden files; allowed suffix. Raises ValueError."""
    base = re.split(r"[\\/]", str(name or "").strip())[-1]
    base = _NAME_BAD.sub("-", base).strip("-")
    base = re.sub(r"-{2,}", "-", base)[:100]
    if not base or base.startswith(".") or base in (".", ".."):
        raise ValueError(f"invalid file name {name!r}")
    if not base.lower().endswith(suffixes):
        raise ValueError(f"file {name!r} must end with one of {', '.join(suffixes)}")
    if base.lower() == "incident.json":
        raise ValueError("reserved file name")
    return base


def experiment_running() -> bool:
    """True if a research experiment (``python -m logagent_rca run``) process is active on this host."""
    for p in psutil.process_iter(["cmdline"]):
        try:
            cmd = p.info["cmdline"] or []
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if "logagent_rca" in cmd and "run" in cmd and "-m" in cmd:
            return True
    return False


class AppService:
    def __init__(self, config_path: str | Path = REPO_ROOT / "configs" / "app.yaml",
                 workspace: Optional[str | Path] = None,
                 llm_factory: Optional[Callable] = None,
                 experiment_guard: Optional[Callable[[], bool]] = None,
                 limits: Optional[UploadLimits] = None):
        self.config_path = Path(config_path)
        self.base_cfg = load_config(self.config_path)
        root = Path(workspace) if workspace else (REPO_ROOT / Path(self.base_cfg.data.cases_dir).parent)
        self.store = InvestigationStore(root)
        self.llm_factory = llm_factory or (lambda cfg: OllamaClient(cfg))
        self.experiment_guard = experiment_guard or (lambda: experiment_running())
        ing = self.base_cfg.ingest
        self.limits = limits or UploadLimits(max_file_bytes=ing.max_bytes_per_file, max_lines=ing.max_lines_per_file)
        self._counter = None
        self._model_cache: dict = {}

    # ------------------------------------------------------------------ configuration
    def config_for(self, inv_id: str) -> Config:
        """The application config with this investigation's directories (validated like any config)."""
        data = self.base_cfg.model_dump(mode="json")
        data["data"].update(cases_dir=str(self.store.cases), truth_dir=str(self.store.no_truth),
                            sums_file=None, sums_sha256=None)
        data["experiment"]["output_dir"] = str(self.store.inv_dir(inv_id))
        if not Path(data["budget"]["tokenizer_file"]).is_absolute():
            data["budget"]["tokenizer_file"] = str(REPO_ROOT / data["budget"]["tokenizer_file"])
        return Config.model_validate(data)

    @property
    def counter(self):
        """The verified Qwen3 token counter (same artefact and hash as the research configuration)."""
        if self._counter is None:
            b = self.base_cfg.budget
            path = b.tokenizer_file if Path(b.tokenizer_file).is_absolute() else str(REPO_ROOT / b.tokenizer_file)
            self._counter = counter_from_config(b.model_copy(update={"tokenizer_file": path}))
        return self._counter

    # ------------------------------------------------------------------ input validation
    def validate_files(self, files: list[tuple[str, bytes]]) -> list[tuple[str, bytes, FileInfo]]:
        lim, errors, out, seen, total = self.limits, {}, [], set(), 0
        if not files:
            raise ValidationProblem({"files": "upload at least one log file"})
        if len(files) > lim.max_files:
            raise ValidationProblem({"files": f"at most {lim.max_files} files"})
        for original, content in files:
            try:
                name = sanitize_filename(original, lim.suffixes)
            except ValueError as exc:
                errors[f"file:{original}"] = str(exc)
                continue
            if name in seen:
                errors[f"file:{original}"] = f"duplicate file name after sanitising: {name}"
                continue
            seen.add(name)
            size = len(content)
            total += size
            if size == 0:
                errors[f"file:{name}"] = "file is empty"
            elif size > lim.max_file_bytes:
                errors[f"file:{name}"] = f"larger than {lim.max_file_bytes} bytes"
            elif b"\x00" in content:
                errors[f"file:{name}"] = "binary content (NUL bytes) is not accepted"
            else:
                lines = content.count(b"\n") + (0 if content.endswith(b"\n") else 1)
                if lines > lim.max_lines:
                    errors[f"file:{name}"] = f"more than {lim.max_lines} lines"
                else:
                    out.append((name, content, FileInfo(name=name, bytes=size, lines=lines,
                                                        sha256=hashlib.sha256(content).hexdigest())))
        if total > lim.max_total_bytes:
            errors["files"] = f"total upload larger than {lim.max_total_bytes} bytes"
        if errors:
            raise ValidationProblem(errors)
        return out

    @staticmethod
    def _parse_time(value) -> datetime:
        if isinstance(value, datetime):
            dt = value
        else:
            text = str(value or "").strip()
            if not text:
                raise ValidationProblem({"timestamp": "required"})
            if not re.search(r"(Z|[+-]\d{2}:?\d{2})$", text):
                raise ValidationProblem({"timestamp": "must include a time zone, e.g. 2026-01-10T10:05:00Z or +05:30"})
            try:
                dt = parse_ts(text)
            except ValueError:
                raise ValidationProblem({"timestamp": "not a valid ISO-8601 timestamp"})
        if dt.tzinfo is None:
            raise ValidationProblem({"timestamp": "must include a time zone"})
        return dt.astimezone(timezone.utc)

    # ------------------------------------------------------------------ create
    def create_investigation(self, files: list[tuple[str, bytes]], incident_id: str, description: str,
                             timestamp, trigger_file: str, trigger_line, trigger_component: str,
                             rule_id: Optional[str] = None, owner: str = "local") -> Investigation:
        accepted = self.validate_files(files)
        names = {n for n, _, _ in accepted}
        errors = {}
        try:
            trig_name = sanitize_filename(trigger_file, self.limits.suffixes)
        except ValueError as exc:
            trig_name, errors["trigger_file"] = None, str(exc)
        if trig_name and trig_name not in names:
            errors["trigger_file"] = f"must be one of the uploaded files: {', '.join(sorted(names))}"
        try:
            line = int(trigger_line)
            if line < 1:
                raise ValueError
        except (TypeError, ValueError):
            errors["trigger_line"] = "must be a positive integer"
            line = None
        ts = None
        try:
            ts = self._parse_time(timestamp)
        except ValidationProblem as vp:
            errors.update(vp.errors)
        if errors:
            raise ValidationProblem(errors)
        inv_id = self.store.new_id()
        try:
            incident = Incident(id=str(incident_id).strip(), rule_id=(rule_id or "manual-entry").strip(),
                                description=str(description).strip(), ts=ts,
                                trigger_uid=f"{trig_name}:{line}", trigger_component=str(trigger_component).strip())
            manifest = CaseManifest(case_id=inv_id, split=Split.DEV, incident=incident, log_files=sorted(names))
        except ValidationError as exc:
            form = {"id": "incident_id", "description": "description", "ts": "timestamp", "rule_id": "rule_id",
                    "trigger_uid": "trigger_line", "trigger_component": "trigger_component"}
            raise ValidationProblem({form.get(str(e["loc"][0]) if e["loc"] else "", "incident"): e["msg"]
                                     for e in exc.errors()})
        staging = self.store.cases / f".staging-{inv_id}"
        staging.mkdir()
        try:
            for name, content, _ in accepted:
                (staging / name).write_bytes(content)
            write_manifest(staging, manifest)
            cfg = self.config_for(inv_id)
            try:
                _, events, stats = load_case(staging, cfg.ingest, cfg.safety.redact)
            except (IngestError, PathViolation) as exc:
                raise ValidationProblem({"trigger_line": str(exc)})
            trig = next(e for e in events if e.uid == incident.trigger_uid)
            if trig.component != incident.trigger_component:
                raise ValidationProblem({"trigger_component": f"line {line} of {trig_name} belongs to component "
                                                              f"{trig.component!r}"})
            lo = ts - timedelta(seconds=cfg.agent.lookback_s)
            hi = ts + timedelta(seconds=120)
            if not lo <= trig.ts <= hi:
                raise ValidationProblem({"timestamp": f"the trigger line is at {trig.ts.isoformat()}, outside the "
                                                      f"analysis window around the incident time"})
            warnings = []
            if stats.unparsed_lines:
                warnings.append(f"{stats.unparsed_lines} line(s) did not match the log format and were skipped")
            if stats.truncated_files:
                warnings.append(f"{stats.truncated_files} file(s) were truncated at the size/line limit")
            if stats.suspicious_events:
                warnings.append(f"{stats.suspicious_events} line(s) look like instructions to an AI model; they are "
                                f"treated as untrusted data and cannot support a diagnosis claim")
            staging.rename(self.store.case_dir(inv_id))
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        inv = Investigation(id=inv_id, created_at=utcnow(), owner=owner, incident=incident,
                            log_files=[fi for _, _, fi in accepted],
                            ingest_stats={k: v for k, v in vars(stats).items() if k != "per_file"} |
                                         {"per_file": stats.per_file},
                            warnings=warnings)
        self.store.inv_dir(inv_id).mkdir(parents=True)
        self.store.save(inv)
        self.store.add_event(inv_id, "input_validated", files=len(accepted), owner=owner)
        self.store.add_event(inv_id, "logs_ingested", events=stats.events, files=stats.files,
                             unparsed_lines=stats.unparsed_lines, suspicious_events=stats.suspicious_events)
        return inv

    # ------------------------------------------------------------------ analysis
    def request_analysis(self, inv_id: str, mode: str, requested_by: str = "local") -> Analysis:
        if mode not in MODES:
            raise ValidationProblem({"mode": f"must be one of {', '.join(MODES)}"})
        holder = {}

        def add(inv: Investigation):
            if any(a.status in ("queued", "running") for a in inv.analyses):
                raise AnalysisRefused("an analysis of this investigation is already queued or running")
            rep = sum(1 for a in inv.analyses if a.mode == mode)
            a = Analysis(run_id=f"{inv.id}__{mode}__r{rep}", mode=mode, repeat=rep, requested_at=utcnow(),
                         requested_by=requested_by)
            inv.analyses.append(a)
            holder["a"] = a
        self.store.update(inv_id, add)
        self.store.add_event(inv_id, "analysis_queued", run_id=holder["a"].run_id, mode=mode)
        return holder["a"]

    def _set(self, inv_id: str, run_id: str, **fields) -> None:
        def upd(inv: Investigation):
            for a in inv.analyses:
                if a.run_id == run_id:
                    for k, v in fields.items():
                        setattr(a, k, v)
        self.store.update(inv_id, upd)

    def run_analysis(self, inv_id: str, run_id: str) -> Optional[RunRecord]:
        """Execute a queued analysis with the existing engine (``runner.run_one``)."""
        inv = self.store.load(inv_id)
        a = next((x for x in inv.analyses if x.run_id == run_id), None)
        if a is None:
            raise KeyError(f"unknown analysis {run_id}")
        if self.experiment_guard():
            self._set(inv_id, run_id, status="error", finished_at=utcnow(),
                      error="refused: the research experiment is running on this host")
            self.store.add_event(inv_id, "analysis_refused", run_id=run_id, reason="experiment_running")
            return None
        with self.store.analysis_lock():
            self._set(inv_id, run_id, status="running", started_at=utcnow())
            self.store.add_event(inv_id, "analysis_started", run_id=run_id, mode=a.mode,
                                 evidence_token_budget=self.base_cfg.budget.evidence_token_budget,
                                 model=self.base_cfg.llm.model)
            try:
                cfg = self.config_for(inv_id)
                commit, dirty = git_commit(REPO_ROOT)
                rec = run_one(cfg, inv_id, ArmId(a.mode), a.repeat, self.store.inv_dir(inv_id),
                              self.llm_factory(cfg.llm), self.counter, self._model_cache, commit)
            except (LLMError, IngestError, PathViolation, OSError, ValueError) as exc:
                self._set(inv_id, run_id, status="error", finished_at=utcnow(), error=str(exc)[:500])
                self.store.add_event(inv_id, "analysis_error", run_id=run_id, error=str(exc)[:500])
                return None
            except Exception as exc:                                   # unexpected: record, do not crash the worker
                self._set(inv_id, run_id, status="error", finished_at=utcnow(), error=f"internal error: {exc}"[:500])
                self.store.add_event(inv_id, "analysis_error", run_id=run_id,
                                     error=traceback.format_exc(limit=3)[-500:])
                return None
        if rec.validation:
            self.store.add_event(inv_id, "report_validated", run_id=run_id,
                                 claims_total=rec.validation.claims_total,
                                 claims_supported=rec.validation.claims_supported,
                                 fabricated_ids=rec.validation.fabricated_ids,
                                 abstained_by_validator=rec.validation.abstained_by_validator)
        self._set(inv_id, run_id, status=rec.status.value, finished_at=utcnow(), error=rec.error)
        self.store.add_event(inv_id, "analysis_finished", run_id=run_id, status=rec.status.value,
                             wall_seconds=rec.metrics.wall_seconds)
        return rec

    def analyze(self, inv_id: str, mode: str, requested_by: str = "local") -> Optional[RunRecord]:
        """Synchronous request + run (CLI)."""
        a = self.request_analysis(inv_id, mode, requested_by)
        return self.run_analysis(inv_id, a.run_id)

    # ------------------------------------------------------------------ queries
    def manifest(self, inv_id: str) -> CaseManifest:
        return CaseManifest.model_validate_json((self.store.case_dir(inv_id) / "incident.json").read_text("utf-8"))

    def record(self, inv_id: str, run_id: Optional[str] = None) -> RunRecord:
        inv = self.store.load(inv_id)
        if run_id is None:
            done = [a for a in inv.analyses if a.status in ("ok", "failed", "aborted")]
            if not done:
                raise KeyError("no completed analysis")
            run_id = done[-1].run_id
        if run_id not in {a.run_id for a in inv.analyses}:
            raise KeyError(f"unknown analysis {run_id}")
        return self.store.load_record(inv_id, run_id)

    def progress(self, inv_id: str, run_id: Optional[str] = None) -> dict:
        inv = self.store.load(inv_id)
        a = next((x for x in inv.analyses if x.run_id == run_id), inv.analyses[-1] if inv.analyses else None)
        events = self.store.events(inv_id, a.run_id if a else None)
        audit = []
        if a:
            for e in self.store.audit_events(inv_id, a.run_id):
                if e.get("kind") in SAFE_AUDIT_KINDS:
                    audit.append({k: e[k] for k in ("ts", "kind", "step", "tool", "args", "new_ids", "repeated_ids",
                                                     "new_tokens", "budget_used", "budget_exhausted", "code", "reason",
                                                     "round", "pending", "evidence_id", "steps", "tool_calls",
                                                     "blocked", "gate_rounds", "status") if k in e})
        return {"investigation": inv.id, "analysis": a.model_dump(mode="json") if a else None,
                "events": events, "agent_events": audit}

    def list_investigations(self, incident_id: Optional[str] = None, mode: Optional[str] = None,
                            date_from: Optional[datetime] = None, date_to: Optional[datetime] = None,
                            owner: Optional[str] = None) -> list[Investigation]:
        out = []
        for inv in self.store.list():
            if owner is not None and inv.owner != owner:
                continue
            if incident_id and incident_id.lower() not in inv.incident.id.lower():
                continue
            if mode and not any(a.mode == mode for a in inv.analyses):
                continue
            if date_from and inv.created_at < date_from:
                continue
            if date_to and inv.created_at > date_to:
                continue
            out.append(inv)
        return out

    def source_lines(self, inv_id: str, source: str, line_no: int, context: int = 2) -> list[dict]:
        """Original lines of an uploaded file around ``line_no`` (for tracing evidence)."""
        man = self.manifest(inv_id)
        if source not in man.log_files:
            raise KeyError("unknown source file")
        path = resolve_inside(self.store.case_dir(inv_id), source)
        lo, hi = max(1, line_no - context), line_no + context
        out = []
        with path.open("rb") as fh:
            for n, raw in enumerate(fh, 1):
                if n > hi:
                    break
                if n >= lo:
                    out.append({"line_no": n, "text": raw.decode("utf-8", errors="replace").rstrip("\r\n")[:2000],
                                "target": n == line_no})
        return out

    # ------------------------------------------------------------------ health and dashboard
    def health(self) -> dict:
        llm = self.base_cfg.llm
        res = {"backend": "ok", "model": llm.model_dump(mode="json"),
               "budget": {"evidence_token_budget": self.base_cfg.budget.evidence_token_budget,
                          "prompt_overhead_tokens": self.base_cfg.budget.prompt_overhead_tokens},
               "agent": self.base_cfg.agent.model_dump(mode="json"),
               "config_file": self.config_path.name, "experiment_running": self.experiment_guard()}
        client = OllamaClient(llm)
        try:
            res["ollama"] = {"reachable": True, "version": client._request("/api/version", timeout=5).get("version")}
            tags = client._request("/api/tags", timeout=5).get("models", [])
            res["ollama"]["models"] = [{"name": m.get("name"), "size": m.get("size"),
                                        "digest": (m.get("digest") or "")[:12]} for m in tags]
            res["ollama"]["configured_model_installed"] = any(m.get("name") == llm.model for m in tags)
        except LLMError as exc:
            res["ollama"] = {"reachable": False, "error": str(exc)[:200]}
        try:
            probe = self.store.root / ".write-probe"
            probe.write_text("ok")
            probe.unlink()
            du = shutil.disk_usage(self.store.root)
            res["persistence"] = {"writable": True, "free_gb": round(du.free / 1e9, 1),
                                  "investigations": sum(1 for _ in self.store.investigations.iterdir())}
        except OSError as exc:
            res["persistence"] = {"writable": False, "error": str(exc)[:200]}
        try:
            res["tokenizer"] = {"verified": True, **self.counter.provenance}
        except Exception as exc:
            res["tokenizer"] = {"verified": False, "error": str(exc)[:200]}
        return res

    def dashboard(self, owner: Optional[str] = None) -> dict:
        invs = self.list_investigations(owner=owner)
        analyses = [a for inv in invs for a in inv.analyses]
        walls = []
        for inv in invs[:50]:
            for a in inv.analyses:
                if a.status in ("ok", "failed", "aborted"):
                    try:
                        walls.append((a.mode, self.store.load_record(inv.id, a.run_id).metrics.wall_seconds))
                    except KeyError:
                        pass
        def med(xs):
            xs = sorted(xs)
            return xs[len(xs) // 2] if xs else None
        return {"investigations": len(invs), "analyses": len(analyses),
                "by_status": {s: sum(1 for a in analyses if a.status == s)
                              for s in ("queued", "running", "ok", "failed", "aborted", "error")},
                "by_mode": {m: sum(1 for a in analyses if a.mode == m) for m in MODES},
                "median_wall_seconds": {m: med([w for mm, w in walls if mm == m]) for m in MODES},
                "recent": [{"id": i.id, "incident": i.incident.id, "created_at": i.created_at.isoformat(),
                            "status": i.status, "modes": [a.mode for a in i.analyses]} for i in invs[:10]],
                "model": self.base_cfg.llm.model, "evidence_token_budget": self.base_cfg.budget.evidence_token_budget}
