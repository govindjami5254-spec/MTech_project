"""CPU and memory sampling of the local Ollama processes during one run (M5). Windows and Linux."""
from __future__ import annotations

import threading
import time
from typing import Optional

import psutil


def _ollama_procs() -> list[psutil.Process]:
    out = []
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (p.info["name"] or "").lower()
            cmd = " ".join(p.info["cmdline"] or []).lower()
            if "ollama" in name or "ollama" in cmd:
                out.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return out


def _cpu_seconds(procs) -> float:
    total = 0.0
    for p in procs:
        try:
            t = p.cpu_times()
            total += t.user + t.system
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total


class ResourceSampler:
    """Context manager: samples RSS and CPU% of Ollama processes every ``interval`` seconds."""

    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self.peak_rss_mb: Optional[float] = None
        self.mean_cpu_percent: Optional[float] = None
        self.cpu_seconds: Optional[float] = None
        self._samples: list[float] = []
        self._stop = threading.Event()

    def _loop(self):
        while not self._stop.is_set():
            procs = _ollama_procs()
            rss, cpu = 0.0, 0.0
            for p in procs:
                try:
                    rss += p.memory_info().rss / 1e6
                    cpu += p.cpu_percent(None)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            self.peak_rss_mb = max(self.peak_rss_mb or 0.0, rss) if procs else self.peak_rss_mb
            if procs:
                self._samples.append(cpu)
            self._stop.wait(self.interval)

    def __enter__(self):
        self._cpu0 = _cpu_seconds(_ollama_procs())
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join(timeout=5)
        self.cpu_seconds = max(0.0, _cpu_seconds(_ollama_procs()) - self._cpu0)
        if self._samples[1:]:                         # first psutil cpu_percent sample is always 0
            self.mean_cpu_percent = sum(self._samples[1:]) / len(self._samples[1:])
        return False

    def as_dict(self) -> dict:
        return {"cpu_seconds": self.cpu_seconds, "peak_rss_mb": self.peak_rss_mb,
                "mean_cpu_percent": self.mean_cpu_percent}
