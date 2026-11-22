"""Validated, immutable experiment configuration (M1).

* Every section forbids unknown keys and is frozen after loading.
* ``data.cases_dir`` and ``data.truth_dir`` must be disjoint: ground truth can never sit
  inside the agent-accessible case root (or vice versa).
* ``budget.evidence_token_budget`` (B) is the strict unique-evidence-token budget shared by
  E2b and E3. The final prompt must fit B plus overhead plus output inside ``num_ctx``.
* ``config_hash`` is computed from the raw (unresolved) values, so it is identical on
  every machine for the same file.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Annotated, Any, Literal, Optional
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from .schemas import ArmId, Split

KNOWN_TOOLS = ("error_timeline", "search_logs", "get_context")   # read-only; no aggregate/count tools

DEFAULT_LOG_FORMAT = {
    "name": "iso-level-component",
    "regex": r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\S+)\s+(?P<level>[A-Za-z]+)\s+"
             r"(?P<component>[A-Za-z0-9][A-Za-z0-9._-]*)\s+(?P<message>.*)$",
}


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LogFormat(_Section):
    name: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    regex: Annotated[str, StringConstraints(min_length=1, max_length=500)]

    @field_validator("regex")
    @classmethod
    def _groups(cls, v):
        try:
            rx = re.compile(v)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc
        missing = {"ts", "level", "message"} - set(rx.groupindex)
        if missing:
            raise ValueError(f"regex must define named groups {sorted(missing)}")
        return v


class IngestConfig(_Section):
    include: Annotated[list[str], Field(min_length=1)] = ["*.log"]
    formats: Annotated[list[LogFormat], Field(min_length=1)] = [LogFormat(**DEFAULT_LOG_FORMAT)]
    max_bytes_per_file: Annotated[int, Field(ge=1_000, le=500_000_000)] = 20_000_000
    max_lines_per_file: Annotated[int, Field(ge=10, le=5_000_000)] = 200_000
    max_message_chars: Annotated[int, Field(ge=40, le=2_000)] = 400

    @field_validator("include")
    @classmethod
    def _globs(cls, v):
        for g in v:
            if ".." in g or g.startswith("/") or "\\" in g:
                raise ValueError(f"unsafe include glob {g!r}")
        return v


class DataConfig(_Section):
    cases_dir: Annotated[str, StringConstraints(min_length=1)]
    truth_dir: Annotated[str, StringConstraints(min_length=1)]
    sums_file: Optional[str] = None                   # SHA256SUMS of the frozen split
    sums_sha256: Optional[Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]] = None

    @property
    def cases_path(self) -> Path:
        return Path(self.cases_dir).resolve()

    @property
    def truth_path(self) -> Path:
        return Path(self.truth_dir).resolve()

    @model_validator(mode="after")
    def _disjoint(self):
        c, t = self.cases_path, self.truth_path
        if c == t or c.is_relative_to(t) or t.is_relative_to(c):
            raise ValueError("truth_dir and cases_dir must be disjoint (ground truth must not be "
                             "reachable from the agent-accessible case root)")
        return self


class LLMConfig(_Section):
    backend: Literal["ollama"] = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    model: Annotated[str, StringConstraints(min_length=1, max_length=80)] = "qwen3:8b"
    num_ctx: Annotated[int, Field(ge=1024, le=131072)] = 8192
    num_predict: Annotated[int, Field(ge=64, le=8192)] = 600     # max output tokens per call
    temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.2
    think: bool = False
    timeout_s: Annotated[int, Field(ge=10, le=7200)] = 900
    max_parse_retries: Annotated[int, Field(ge=0, le=3)] = 1

    @field_validator("base_url")
    @classmethod
    def _url(cls, v):
        u = urlparse(v)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ValueError("base_url must be an http(s) URL")
        return v.rstrip("/")


class BudgetConfig(_Section):
    evidence_token_budget: Annotated[int, Field(ge=100, le=100_000)] = 3000     # B
    prompt_overhead_tokens: Annotated[int, Field(ge=0, le=20_000)] = 1500      # system + schema + framing
    token_counter: Literal["hf_tokenizer"] = "hf_tokenizer"                     # exact model tokenizer (M2)
    tokenizer_file: Annotated[str, StringConstraints(min_length=1)] = "models/qwen3-tokenizer.json"
    tokenizer_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] = (
        "aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4")
    tokenizer_source: str = ("https://huggingface.co/Qwen/Qwen3-8B/resolve/"
                             "b968826d9c46dd6066d109eabc6255188de91218/tokenizer.json")
    tokenizers_version: Literal["0.23.3"] = "0.23.3"


class AgentConfig(_Section):
    max_steps: Annotated[int, Field(ge=1, le=30)] = 6
    min_tool_calls: Annotated[int, Field(ge=0, le=10)] = 2
    coverage_gate: bool = True                 # A2 sets this to false
    max_gate_rounds: Annotated[int, Field(ge=0, le=5)] = 2
    gate_extra_steps: Annotated[int, Field(ge=0, le=10)] = 2
    lookback_s: Annotated[int, Field(ge=10, le=86_400)] = 600
    max_run_seconds: Annotated[int, Field(ge=10, le=14_400)] = 1200
    max_blocked_calls: Annotated[int, Field(ge=1, le=20)] = 3

    @model_validator(mode="after")
    def _steps(self):
        if self.min_tool_calls > self.max_steps:
            raise ValueError("min_tool_calls cannot exceed max_steps")
        return self


class ValidatorConfig(_Section):
    enabled: bool = True                       # raw output is always logged, so A3 needs no reruns
    min_overlap_tokens: Annotated[int, Field(ge=1, le=10)] = 2


class SafetyConfig(_Section):
    allowed_tools: Annotated[list[str], Field(min_length=1)] = list(KNOWN_TOOLS)
    redact: bool = True
    max_tool_output_events: Annotated[int, Field(ge=1, le=200)] = 25
    max_tool_output_chars: Annotated[int, Field(ge=200, le=50_000)] = 4000

    @field_validator("allowed_tools")
    @classmethod
    def _known(cls, v):
        unknown = sorted(set(v) - set(KNOWN_TOOLS))
        if unknown:
            raise ValueError(f"unknown tools in allowlist: {unknown}")
        if len(set(v)) != len(v):
            raise ValueError("duplicate tool in allowlist")
        return v


class ExperimentConfig(_Section):
    name: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
    split: Split
    arms: Annotated[list[ArmId], Field(min_length=1)]
    repeats: Annotated[int, Field(ge=1, le=20)] = 3
    base_seed: int = 1000
    output_dir: Annotated[str, StringConstraints(min_length=1)] = "runs"

    @field_validator("arms")
    @classmethod
    def _arms(cls, v):
        if len(set(v)) != len(v):
            raise ValueError("duplicate arm")
        if ArmId.A3 in v and ArmId.E3 not in v:
            raise ValueError("A3 is scored from E3 runs; include E3")
        return v

    def seed_for(self, repeat: int) -> int:
        return self.base_seed + repeat


class Config(_Section):
    config_version: Literal["1"] = "1"
    data: DataConfig
    experiment: ExperimentConfig
    ingest: IngestConfig = IngestConfig()
    llm: LLMConfig = LLMConfig()
    budget: BudgetConfig = BudgetConfig()
    agent: AgentConfig = AgentConfig()
    validator: ValidatorConfig = ValidatorConfig()
    safety: SafetyConfig = SafetyConfig()

    @model_validator(mode="after")
    def _context_fits(self):
        need = (self.budget.evidence_token_budget + self.budget.prompt_overhead_tokens
                + self.llm.num_predict)
        if need > self.llm.num_ctx:
            raise ValueError(f"B + prompt overhead + num_predict = {need} exceeds num_ctx "
                             f"{self.llm.num_ctx}; the final call could not hold all evidence")
        out = Path(self.experiment.output_dir).resolve()
        if out.is_relative_to(self.data.cases_path):
            raise ValueError("output_dir must not be inside cases_dir")
        return self


# ---------------------------------------------------------------- loading
def _set_dotted(data: dict, dotted: str, value: Any) -> None:
    keys = dotted.split(".")
    node = data
    for k in keys[:-1]:
        node = node.setdefault(k, {})
        if not isinstance(node, dict):
            raise ValueError(f"cannot override {dotted}: {k} is not a section")
    node[keys[-1]] = value


def load_config(path: str | Path, overrides: Optional[dict[str, Any]] = None) -> Config:
    """Load YAML, apply dotted overrides (e.g. ``{"agent.coverage_gate": False}``), validate."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("config root must be a mapping")
    for dotted, value in (overrides or {}).items():
        _set_dotted(raw, dotted, value)
    return Config.model_validate(raw)


def config_hash(cfg: Config) -> str:
    """SHA-256 over canonical JSON of the raw configuration values."""
    canonical = json.dumps(cfg.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_override(item: str) -> tuple[str, Any]:
    """'agent.max_steps=4' -> ('agent.max_steps', 4); values are parsed as YAML scalars."""
    key, sep, value = item.partition("=")
    if not sep or not key.strip():
        raise ValueError(f"override must be KEY=VALUE: {item!r}")
    return key.strip(), yaml.safe_load(value)
