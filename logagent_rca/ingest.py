"""Safe, bounded log ingestion for one case bundle (M2).

Security and determinism rules:
* Only files listed in the case manifest are read, and each must resolve inside the case
  directory (no ``..``, absolute paths or symlinks escaping it). Ground truth lives outside
  the case directory (enforced by config), so it is unreachable from here.
* Reads are bounded by bytes and lines per file; invalid UTF-8 is replaced, not fatal.
* Log text is untrusted: it is Unicode-normalised (NFC), stripped of control, zero-width and
  bidirectional-override characters, whitespace-collapsed, redacted, neutralised against our
  own prompt delimiters and citation labels, truncated, and flagged if it looks like an
  instruction to the model.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import IngestConfig
from .schemas import CaseManifest, LogEvent, normalize_severity

MANIFEST_NAME = "incident.json"


class IngestError(Exception):
    pass


class PathViolation(IngestError):
    pass


# ------------------------------------------------------------------ sanitising
_REDACTIONS = [
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\s*[=:]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer [REDACTED]"),
    (re.compile(r"\b(?:sk|pk|ghp|AKIA)[A-Za-z0-9_\-]{12,}\b"), "[REDACTED_KEY]"),
    (re.compile(r"\b[\w.+\-]+@[\w\-]+\.[\w.\-]+\b"), "[REDACTED_EMAIL]"),
]
# C0/C1 controls (tab, VT, FF, CR, NEL are whitespace and collapse to a space), zero-width,
# bidi overrides/isolates, BOM.
_INVISIBLE = re.compile("[\u0000-\u0008\u000e-\u001f\u007f-\u0084\u0086-\u009f"
                        "\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")
_WS = re.compile(r"\s+")
_DELIMS = re.compile(r"</?\s*log_data\s*>", re.IGNORECASE)
_FAKE_CITATION = re.compile(r"\[\s*(E\d+)\s*\]")          # "[E12]" in a log line would forge a citation
_INJECTION = re.compile(
    r"(?i)(ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+instructions"
    r"|disregard\s+(the\s+)?(previous|above|system)"
    r"|you\s+are\s+now\b|system\s+prompt|new\s+instructions?\s*:"
    r"|\bcall\s+(the\s+)?tool\b|\brun_shell\b|\brm\s+-rf\b|\bexec(ute)?\s*\("
    r"|\broot\s+cause\s+is\b.*\b(report|answer|respond)\b)")


def sanitize_message(text: str, max_chars: int, redact: bool = True) -> str:
    text = unicodedata.normalize("NFC", text)
    text = _INVISIBLE.sub("", text)
    text = _WS.sub(" ", text).strip()
    if redact:
        for pattern, repl in _REDACTIONS:
            text = pattern.sub(repl, text)
    text = _DELIMS.sub("[log_data]", text)
    text = _FAKE_CITATION.sub(r"(\1)", text)
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION.search(text))


_COMPONENT_BAD = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_component(raw: str) -> Optional[str]:
    c = _COMPONENT_BAD.sub("-", raw.strip()).strip("-.")[:64]
    if not c or not c[0].isalnum():
        return None
    return c


def parse_ts(value: str) -> datetime:
    """ISO-8601; 'Z' and comma decimals accepted; naive timestamps are assumed UTC."""
    s = value.strip().replace(",", ".")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ------------------------------------------------------------------ path safety
def resolve_inside(root: Path, rel: str) -> Path:
    root = root.resolve()
    if Path(rel).is_absolute():
        raise PathViolation(f"absolute path not allowed: {rel}")
    full = (root / rel).resolve()
    if not full.is_relative_to(root):
        raise PathViolation(f"path escapes case directory: {rel}")
    return full


# ------------------------------------------------------------------ loading
@dataclass
class IngestStats:
    files: int = 0
    lines_read: int = 0
    events: int = 0
    unparsed_lines: int = 0
    continuation_lines: int = 0
    truncated_files: int = 0
    bad_timestamps: int = 0
    bad_components: int = 0
    suspicious_events: int = 0
    per_file: dict = field(default_factory=dict)


def load_manifest(case_dir: str | Path) -> CaseManifest:
    path = resolve_inside(Path(case_dir), MANIFEST_NAME)
    if not path.is_file():
        raise IngestError(f"missing {MANIFEST_NAME} in {case_dir}")
    return CaseManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _read_bounded(path: Path, cfg: IngestConfig, stats: IngestStats) -> list[str]:
    lines, used = [], 0
    with path.open("rb") as fh:
        for raw in fh:
            used += len(raw)
            if len(lines) >= cfg.max_lines_per_file or used > cfg.max_bytes_per_file:
                stats.truncated_files += 1
                break
            lines.append(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
    return lines


def load_events(case_dir: str | Path, log_files: list[str], cfg: IngestConfig,
                redact: bool = True) -> tuple[list[LogEvent], IngestStats]:
    root = Path(case_dir).resolve()
    formats = [re.compile(f.regex) for f in cfg.formats]
    stats = IngestStats()
    events: list[LogEvent] = []
    for rel in log_files:
        path = resolve_inside(root, rel)
        if path.is_symlink() or not path.is_file():
            raise PathViolation(f"not a regular file inside the case directory: {rel}")
        stats.files += 1
        raw_events: list[dict] = []
        pending: Optional[dict] = None
        for n, line in enumerate(_read_bounded(path, cfg, stats), 1):
            stats.lines_read += 1
            if not line.strip():
                continue
            m = next((rx.match(line) for rx in formats if rx.match(line)), None)
            if m:
                try:
                    ts = parse_ts(m.group("ts"))
                    sev = normalize_severity(m.group("level"))
                except ValueError:
                    stats.bad_timestamps += 1
                    m = None
            if m:
                gd = m.groupdict()
                comp = sanitize_component(gd.get("component") or path.stem)
                if comp is None:
                    stats.bad_components += 1
                    pending = None
                    continue
                pending = {"ts": ts, "sev": sev, "comp": comp, "msg": gd["message"], "line": n}
                raw_events.append(pending)
            elif pending is not None and line[:1].isspace():
                stats.continuation_lines += 1
                if len(pending["msg"]) < cfg.max_message_chars:      # stack-trace continuation
                    pending["msg"] += " | " + line.strip()
            else:
                stats.unparsed_lines += 1
        count = 0
        for r in raw_events:
            msg = sanitize_message(r["msg"], cfg.max_message_chars, redact)
            sus = looks_like_injection(msg)
            stats.suspicious_events += int(sus)
            events.append(LogEvent(uid=f"{rel}:{r['line']}", ts=r["ts"], severity=r["sev"],
                                   component=r["comp"], message=msg, source=rel,
                                   line_no=r["line"], suspicious=sus))
            count += 1
        stats.per_file[rel] = count
    stats.events = len(events)
    return events, stats


def load_case(case_dir: str | Path, cfg: IngestConfig, redact: bool = True):
    """Read ``incident.json`` and the listed logs. Returns (manifest, events, stats)."""
    manifest = load_manifest(case_dir)
    events, stats = load_events(case_dir, manifest.log_files, cfg, redact)
    if not any(e.uid == manifest.incident.trigger_uid for e in events):
        raise IngestError(f"trigger event {manifest.incident.trigger_uid} not found in case logs")
    return manifest, events, stats


def write_manifest(case_dir: str | Path, manifest: CaseManifest) -> Path:
    path = Path(case_dir) / MANIFEST_NAME
    path.write_text(json.dumps(manifest.model_dump(mode="json"), indent=2), encoding="utf-8")
    return path
