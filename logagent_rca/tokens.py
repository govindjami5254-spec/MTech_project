"""Exact token counting with the model's own tokenizer (M2).

The evidence-token budget B is counted with Qwen3's ``tokenizer.json`` via the pinned
``tokenizers`` package. The artifact's SHA-256 and the package version are verified on load,
so a different tokenizer can never silently change B.

What this counts: the text we pass in, without special tokens. It does NOT count chat-template
tokens, the system prompt, or other prompt framing; Ollama's ``prompt_eval_count`` includes those
(and may exclude prefix-cached tokens), so the two numbers are not expected to be equal.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import tokenizers
from tokenizers import Tokenizer


class TokenizerMismatch(RuntimeError):
    pass


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...

    @property
    def provenance(self) -> dict: ...


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class HFTokenCounter:
    """Counts tokens with a verified ``tokenizer.json`` (no special tokens added)."""

    def __init__(self, tokenizer_file: str | Path, expected_sha256: str, expected_version: str):
        path = Path(tokenizer_file)
        if not path.is_file():
            raise FileNotFoundError(f"tokenizer file not found: {path} (download it from the URL in "
                                    f"budget.tokenizer_source)")
        actual = sha256_file(path)
        if actual != expected_sha256:
            raise TokenizerMismatch(f"tokenizer sha256 {actual} != expected {expected_sha256}")
        if tokenizers.__version__ != expected_version:
            raise TokenizerMismatch(f"tokenizers {tokenizers.__version__} != pinned {expected_version}")
        self._tok = Tokenizer.from_file(str(path))
        self._provenance = {"tokenizer_file": path.name, "tokenizer_sha256": actual,
                            "tokenizers_version": tokenizers.__version__,
                            "vocab_size": self._tok.get_vocab_size()}
        self._cached = lru_cache(maxsize=65536)(self._count_uncached)

    def _count_uncached(self, text: str) -> int:
        return len(self._tok.encode(text, add_special_tokens=False).ids)

    def count(self, text: str) -> int:
        if not text:
            return 0
        return self._cached(text)

    @property
    def provenance(self) -> dict:
        return dict(self._provenance)


def counter_from_config(budget_cfg) -> HFTokenCounter:
    return HFTokenCounter(budget_cfg.tokenizer_file, budget_cfg.tokenizer_sha256,
                          budget_cfg.tokenizers_version)
