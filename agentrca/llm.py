"""LLM backends behind one small interface (Ollama for real runs, scripted for tests)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .config import LLMConfig


class LLMError(Exception):
    pass


@dataclass
class ToolCall:
    name: str
    args: Any


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0
    raw_message: dict = field(default_factory=dict)

    def message(self) -> dict:
        if self.raw_message:
            return self.raw_message
        msg: dict = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [{"function": {"name": t.name, "arguments": t.args}}
                                 for t in self.tool_calls]
        return msg


class OllamaClient:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg

    def _post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(
            self.cfg.base_url.rstrip("/") + path, json.dumps(body).encode("utf-8"),
            {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout_s) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LLMError(f"Ollama request failed: {exc}") from exc

    def chat(self, messages: list, tools: Optional[list] = None,
             schema: Optional[dict] = None) -> LLMResponse:
        body: dict = {
            "model": self.cfg.model, "messages": messages, "stream": False,
            "think": self.cfg.think,
            "options": {"num_ctx": self.cfg.num_ctx, "temperature": self.cfg.temperature,
                        "seed": self.cfg.seed},
        }
        if tools:
            body["tools"] = tools
        if schema:
            body["format"] = schema
        t0 = time.monotonic()
        data = self._post("/api/chat", body)
        msg = data.get("message", {}) or {}
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    pass
            calls.append(ToolCall(fn.get("name", ""), args))
        return LLMResponse(content=msg.get("content", "") or "", tool_calls=calls,
                           tokens_in=data.get("prompt_eval_count", 0),
                           tokens_out=data.get("eval_count", 0),
                           seconds=time.monotonic() - t0, raw_message=msg)

    def check(self) -> None:
        """Fail fast with a clear message if the server or model is unavailable."""
        try:
            req = urllib.request.Request(self.cfg.base_url.rstrip("/") + "/api/tags")
            with urllib.request.urlopen(req, timeout=10) as r:
                names = [m.get("name", "") for m in json.loads(r.read()).get("models", [])]
        except Exception as exc:
            raise LLMError(f"Cannot reach Ollama at {self.cfg.base_url} ({exc}). Start it with 'ollama serve'.") from exc
        if self.cfg.model not in names and f"{self.cfg.model}:latest" not in names:
            raise LLMError(f"Model '{self.cfg.model}' is not installed in Ollama. Run: ollama pull {self.cfg.model}")

    def model_memory_bytes(self) -> Optional[int]:
        """Memory Ollama reports for the loaded model (portable alternative to process sampling)."""
        try:
            req = urllib.request.Request(self.cfg.base_url.rstrip("/") + "/api/ps")
            with urllib.request.urlopen(req, timeout=10) as r:
                for m in json.loads(r.read()).get("models", []):
                    if m.get("name", "").startswith(self.cfg.model.split(":")[0]):
                        return int(m.get("size", 0))
        except Exception:
            return None
        return None


class ScriptedLLM:
    """Deterministic stand-in used by tests: `script(messages, tools, schema) -> LLMResponse`."""

    def __init__(self, script: Callable[[list, Optional[list], Optional[dict]], LLMResponse]):
        self.script = script
        self.calls = 0

    def chat(self, messages, tools=None, schema=None) -> LLMResponse:
        self.calls += 1
        return self.script(messages, tools, schema)

    def model_memory_bytes(self):
        return None


def make_llm(cfg: LLMConfig):
    if cfg.backend == "ollama":
        return OllamaClient(cfg)
    raise ValueError(f"unsupported llm backend: {cfg.backend}")
