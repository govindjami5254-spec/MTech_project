"""Background analysis worker for the web adapter.

One worker thread executes queued analyses one at a time, because the local Ollama server runs with a single
parallel slot. The service's cross-process lock additionally serialises web and CLI analyses. Web requests only
enqueue work and return immediately.
"""
from __future__ import annotations

import queue
import threading

from ..service import AppService
from ..store import utcnow


class JobWorker:
    def __init__(self, service: AppService):
        self.service = service
        self.q: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name="lrca-analysis-worker", daemon=True)
        self._stop = threading.Event()

    def start(self) -> None:
        self._recover()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.q.put(("", ""))

    def submit(self, inv_id: str, run_id: str) -> None:
        self.q.put((inv_id, run_id))

    def pending(self) -> int:
        return self.q.qsize()

    def _recover(self) -> None:
        """After a restart: re-queue queued analyses; mark interrupted running analyses as errors."""
        for inv in self.service.store.list():
            for a in inv.analyses:
                if a.status == "queued":
                    self.submit(inv.id, a.run_id)
                elif a.status == "running":
                    self.service._set(inv.id, a.run_id, status="error", finished_at=utcnow(),
                                      error="interrupted: the server stopped during the analysis")
                    self.service.store.add_event(inv.id, "analysis_interrupted", run_id=a.run_id)

    def _loop(self) -> None:
        while not self._stop.is_set():
            inv_id, run_id = self.q.get()
            if not inv_id:
                break
            try:
                self.service.run_analysis(inv_id, run_id)
            except Exception as exc:                       # never let the worker die
                try:
                    self.service._set(inv_id, run_id, status="error", finished_at=utcnow(),
                                      error=f"internal error: {exc}"[:500])
                except Exception:
                    pass
            finally:
                self.q.task_done()

    def drain(self, timeout: float = 30.0) -> None:
        """Block until all queued work is done (tests)."""
        import time
        end = time.monotonic() + timeout
        while self.q.unfinished_tasks and time.monotonic() < end:
            time.sleep(0.05)
