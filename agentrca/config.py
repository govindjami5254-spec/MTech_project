"""Configuration loading (YAML -> dataclasses with safe defaults)."""
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_FORMATS = [
    {
        "name": "iso-level-component",
        "regex": r"^(?P<ts>\d{4}-\d{2}-\d{2}[T ]\S+)\s+(?P<level>[A-Za-z]+)\s+"
                 r"(?P<component>[\w.\-]+)\s+(?P<message>.*)$",
    },
]


@dataclass
class LogsConfig:
    root: str = "data/demo"
    include: list = field(default_factory=lambda: ["*.log"])
    formats: list = field(default_factory=lambda: list(DEFAULT_FORMATS))
    max_bytes_per_file: int = 20_000_000
    max_lines_per_file: int = 200_000
    max_message_chars: int = 400


@dataclass
class AgentConfig:
    max_steps: int = 8
    min_tool_calls: int = 2
    lookback_s: int = 600
    coverage_gate: bool = True
    max_gate_rounds: int = 2
    gate_extra_steps: int = 3          # extra LLM steps granted per gate round
    validate: bool = True
    max_tool_output_events: int = 25
    max_tool_output_chars: int = 4000
    max_final_evidence: int = 40
    max_run_seconds: int = 900
    max_blocked_calls: int = 3
    single_tail_events: int = 20        # baseline B2: last N events before the incident
    static_per_component: int = 3       # baseline B3: events retrieved per problem component


@dataclass
class LLMConfig:
    backend: str = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen3:8b"
    num_ctx: int = 8192
    temperature: float = 0.0
    seed: int = 42
    think: bool = False
    timeout_s: int = 900


@dataclass
class SafetyConfig:
    redact: bool = True
    quarantine_suspicious: bool = False   # hide suspected prompt-injection text from the LLM
    allowed_tools: list = field(default_factory=lambda: [
        "list_components", "search_logs", "get_context", "count_matches", "error_timeline",
    ])


@dataclass
class Config:
    logs: LogsConfig = field(default_factory=LogsConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    rules_file: str = "rules.yaml"
    output_dir: str = "runs"


def _merge(obj: Any, data: dict, path: str = "") -> None:
    valid = {f.name: f for f in fields(obj)}
    for key, value in (data or {}).items():
        if key not in valid:
            raise ValueError(f"Unknown config key: {path}{key}")
        current = getattr(obj, key)
        if is_dataclass(current):
            _merge(current, value, f"{path}{key}.")
        else:
            setattr(obj, key, value)


def load_config(path: str | None = None, overrides: dict | None = None) -> Config:
    cfg = Config()
    if path:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        _merge(cfg, data)
    for dotted, value in (overrides or {}).items():
        target = cfg
        parts = dotted.split(".")
        for p in parts[:-1]:
            target = getattr(target, p)
        if not hasattr(target, parts[-1]):
            raise ValueError(f"Unknown config key: {dotted}")
        setattr(target, parts[-1], value)
    return cfg


def parse_override_value(raw: str) -> Any:
    low = raw.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw
