"""Ollama client with full provenance and usage accounting, plus a scripted fake for tests (M5)."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .config import LLMConfig
from .schemas import ModelInfo


class LLMError(RuntimeError):
    pass


@dataclass
class ToolCall:
    name: str
    args: Any


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list = field(default_factory=list)
    prompt_tokens: int = 0         # Ollama prompt_eval_count (template + all messages)
    output_tokens: int = 0         # Ollama eval_count
    seconds: float = 0.0
    raw_message: dict = field(default_factory=dict)

    def as_message(self) -> dict:
        if self.raw_message:
            return {k: v for k, v in self.raw_message.items() if k in ("role", "content", "tool_calls")}
        msg: dict = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [{"function": {"name": t.name, "arguments": t.args}} for t in self.tool_calls]
        return msg


class OllamaClient:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg

    def _request(self, path: str, body: Optional[dict] = None, timeout: Optional[int] = None) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.cfg.base_url + path, data,
                                     {"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.cfg.timeout_s) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise LLMError(f"Ollama request {path} failed: {exc}") from exc

    def model_info(self, seed: int) -> ModelInfo:
        tags = {m["name"]: m for m in self._request("/api/tags", timeout=30)["models"]}
        if self.cfg.model not in tags:
            raise LLMError(f"model {self.cfg.model} not installed; available: {sorted(tags)}")
        show = self._request("/api/show", {"model": self.cfg.model}, timeout=30)
        m = re.search(r"sha256-([0-9a-f]{64})", show.get("modelfile", ""))
        det = show.get("details", {})
        return ModelInfo(name=self.cfg.model, manifest_digest=tags[self.cfg.model]["digest"],
                         weights_digest=m.group(1) if m else None,
                         quantization=det.get("quantization_level"), parameter_size=det.get("parameter_size"),
                         ollama_version=self._request("/api/version", timeout=30).get("version"),
                         num_ctx=self.cfg.num_ctx, temperature=self.cfg.temperature, seed=seed,
                         think=self.cfg.think, num_predict=self.cfg.num_predict)

    def chat(self, messages: list, seed: int, tools: Optional[list] = None,
             schema: Optional[dict] = None) -> LLMResponse:
        body: dict = {"model": self.cfg.model, "messages": messages, "stream": False, "think": self.cfg.think,
                      "keep_alive": "60m",
                      "options": {"num_ctx": self.cfg.num_ctx, "temperature": self.cfg.temperature,
                                  "seed": seed, "num_predict": self.cfg.num_predict}}
        if tools:
            body["tools"] = tools
        if schema:
            body["format"] = schema
        t0 = time.monotonic()
        data = self._request("/api/chat", body)
        msg = data.get("message") or {}
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    pass
            calls.append(ToolCall(str(fn.get("name", "")), args))
        return LLMResponse(content=msg.get("content") or "", tool_calls=calls,
                           prompt_tokens=int(data.get("prompt_eval_count") or 0),
                           output_tokens=int(data.get("eval_count") or 0),
                           seconds=time.monotonic() - t0, raw_message=msg)


class ScriptedLLM:
    """Deterministic stand-in: ``script(messages, tools, schema) -> LLMResponse``."""

    def __init__(self, script: Callable[[list, Optional[list], Optional[dict]], LLMResponse]):
        self.script = script
        self.calls: list[list] = []

    def chat(self, messages, seed, tools=None, schema=None) -> LLMResponse:
        self.calls.append([dict(m) for m in messages])
        return self.script(messages, tools, schema)

    def model_info(self, seed: int) -> ModelInfo:
        return ModelInfo(name="scripted", manifest_digest="0" * 64, num_ctx=8192, temperature=0.0,
                         seed=seed, think=False, num_predict=600)
