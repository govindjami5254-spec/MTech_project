"""CPU and memory measurement of the local Ollama process tree during one run (M5, corrected M11).

What is measured (Linux and Windows via psutil; unavailable values are recorded as None):

* Process tree: every ``ollama`` server process (matched by process *name* or executable basename,
  never by command-line text) plus all of its descendants (e.g. ``llama-server`` runners). Each PID is
  counted once per sample.
* ``peak_rss_mb``: peak over samples of the summed resident set size of the tree. RSS counts shared
  pages once per process, so with several processes it can over-state physical memory.
* ``peak_uss_mb``: peak summed unique set size (memory freed if the processes exited). Never
  double-counts; available on Linux/macOS/Windows where psutil supports ``memory_full_info``.
* ``peak_pss_mb``: peak summed proportional set size (shared pages divided among sharers). Linux only.
* ``host_used_peak_mb`` / ``host_total_mb``: host-wide memory in use (``total - available``) and total.
  On a shared server this includes other users' processes and is context only.
* ``cpu_seconds``: user+system CPU time consumed by the tree during the run; ``mean_cpu_percent``:
  ``100 * cpu_seconds / wall time`` (100 = one core fully busy). (The M5 version used per-sample
  ``cpu_percent`` on freshly created process objects, which psutil always reports as 0 after M11's
  tree rewrite; the time-based definition avoids that.)

Note (M11 investigation): with Ollama 0.40.16 the runner (llama-server) loads weights without mmap
and keeps a host-RAM prompt cache (log: "prompt cache is enabled, size limit: 8192 MiB"). During the
dev pilot the cache reached 8,178 MiB (log "cache state" lines), so the runner's own memory grew from
~6.8 GB after loading to ~15 GB. That is real, unshared process memory, not double counting.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Callable, Iterable, Optional

import psutil

FULL_INFO_EVERY = 4          # memory_full_info reads /proc/<pid>/smaps: sample it every 4th tick


def _is_ollama_server(p) -> bool:
    try:
        name = (p.name() or "").lower()
        exe = os.path.basename(p.exe() or "").lower() if hasattr(p, "exe") else ""
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return False
    return name in ("ollama", "ollama.exe") or exe in ("ollama", "ollama.exe")


def ollama_tree(iter_procs: Callable[[], Iterable] = psutil.process_iter) -> list:
    """Ollama server processes and all their descendants, each PID once."""
    seen: dict[int, object] = {}
    for p in iter_procs():
        if _is_ollama_server(p):
            seen.setdefault(p.pid, p)
            try:
                for child in p.children(recursive=True):
                    seen.setdefault(child.pid, child)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    return [seen[k] for k in sorted(seen)]


def sample_memory(procs: list, full: bool) -> dict:
    """Summed RSS (always) and USS/PSS (when ``full`` and available) over distinct processes, in MB."""
    rss, uss, pss, have_uss, have_pss = 0.0, 0.0, 0.0, False, False
    for p in procs:
        try:
            rss += p.memory_info().rss / 1e6
            if full:
                fi = p.memory_full_info()
                if getattr(fi, "uss", None) is not None:
                    uss += fi.uss / 1e6
                    have_uss = True
                if getattr(fi, "pss", None) is not None:
                    pss += fi.pss / 1e6
                    have_pss = True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
            continue
    return {"rss": rss, "uss": uss if have_uss else None, "pss": pss if have_pss else None}


def _cpu_seconds(procs) -> float:
    total = 0.0
    for p in procs:
        try:
            t = p.cpu_times()
            total += t.user + t.system
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return total


def _peak(cur: Optional[float], new: Optional[float]) -> Optional[float]:
    if new is None:
        return cur
    return new if cur is None else max(cur, new)


class ResourceSampler:
    """Context manager sampling the Ollama process tree every ``interval`` seconds."""

    def __init__(self, interval: float = 0.5, tree: Callable[[], list] = ollama_tree):
        self.interval = interval
        self._tree = tree
        self.peak_rss_mb: Optional[float] = None
        self.peak_uss_mb: Optional[float] = None
        self.peak_pss_mb: Optional[float] = None
        self.host_used_peak_mb: Optional[float] = None
        self.host_total_mb: Optional[float] = None
        self.mean_cpu_percent: Optional[float] = None
        self.cpu_seconds: Optional[float] = None
        self._stop = threading.Event()
        self._tick = 0

    def _record_cpu(self, procs) -> None:
        for p in procs:
            try:
                t = p.cpu_times()
                self._cpu_last[p.pid] = t.user + t.system
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

    def _sample(self):
        procs = self._tree()
        full = self._tick % FULL_INFO_EVERY == 0
        self._tick += 1
        if procs:
            m = sample_memory(procs, full)
            self.peak_rss_mb = _peak(self.peak_rss_mb, m["rss"])
            self.peak_uss_mb = _peak(self.peak_uss_mb, m["uss"])
            self.peak_pss_mb = _peak(self.peak_pss_mb, m["pss"])
            self._record_cpu(procs)
        try:
            vm = psutil.virtual_memory()
            self.host_total_mb = vm.total / 1e6
            self.host_used_peak_mb = _peak(self.host_used_peak_mb, (vm.total - vm.available) / 1e6)
        except Exception:                                   # pragma: no cover - platform specific
            pass

    def _loop(self):
        while not self._stop.is_set():
            self._sample()
            self._stop.wait(self.interval)

    def __enter__(self):
        self._cpu_last: dict[int, float] = {}
        self._record_cpu(self._tree())
        self._cpu_first = dict(self._cpu_last)        # processes started later begin at 0
        self._t0 = time.monotonic()
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join(timeout=5)
        self._record_cpu(self._tree())
        self.cpu_seconds = sum(max(0.0, last - self._cpu_first.get(pid, 0.0))
                               for pid, last in self._cpu_last.items())
        elapsed = time.monotonic() - self._t0
        if self._cpu_last and elapsed > 0:          # mean utilisation over the run; 100 = one core
            self.mean_cpu_percent = 100.0 * self.cpu_seconds / elapsed
        return False

    def as_dict(self) -> dict:
        return {"cpu_seconds": self.cpu_seconds, "mean_cpu_percent": self.mean_cpu_percent,
                "peak_rss_mb": self.peak_rss_mb, "peak_uss_mb": self.peak_uss_mb, "peak_pss_mb": self.peak_pss_mb,
                "host_used_peak_mb": self.host_used_peak_mb, "host_total_mb": self.host_total_mb}
