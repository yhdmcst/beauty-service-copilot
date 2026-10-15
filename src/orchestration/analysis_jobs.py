"""Bounded background inference jobs for the single-machine demo."""

from __future__ import annotations

import logging
import threading
import uuid
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from src.ops.case_store import now

logger = logging.getLogger(__name__)


class QueueFull(RuntimeError):
    """No further inference work can be admitted."""


class AnalysisJobs:
    """Bound workers and outstanding work; active exact repeats share one job."""

    def __init__(self, workers: int = 1, capacity: int = 3, history_limit: int = 128) -> None:
        if workers < 1 or capacity < workers or history_limit < capacity:
            raise ValueError("Invalid inference queue limits")
        self.workers, self.capacity, self.history_limit = workers, capacity, history_limit
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="beauty-assist")
        self._lock = threading.RLock()
        self._slots = threading.BoundedSemaphore(capacity)
        self._jobs: OrderedDict[str, dict] = OrderedDict()
        self._active: dict[str, str] = {}
        self._submitted: dict[str, float] = {}

    def submit(self, key: str, session_id: str, work: Callable[[], dict]) -> dict:
        """Return immediately; do not admit unbounded model requests."""
        with self._lock:
            if key in self._active:
                return dict(self._jobs[self._active[key]])
            if not self._slots.acquire(blocking=False):
                raise QueueFull("Inference queue is full; saved risk tasks remain available")
            job_id = str(uuid.uuid4())
            job = {
                "job_id": job_id, "session_id": session_id, "status": "queued",
                "created_at": now(), "updated_at": now(), "result": None, "error": None,
            }
            self._jobs[job_id] = job
            self._submitted[job_id] = time.perf_counter()
            self._active[key] = job_id
            try:
                self._pool.submit(self._run, job_id, key, work)
            except RuntimeError:
                self._slots.release()
                self._active.pop(key)
                self._jobs.pop(job_id)
                self._submitted.pop(job_id)
                raise
            return dict(job)

    def _run(self, job_id: str, key: str, work: Callable[[], dict]) -> None:
        started = time.perf_counter()
        with self._lock:
            self._jobs[job_id].update(
                status="running", updated_at=now(),
                queue_wait_ms=round((started - self._submitted[job_id]) * 1000, 2))
        try:
            result = work()
        except Exception as error:
            logger.exception("Background analysis %s failed", job_id)
            with self._lock:
                self._jobs[job_id].update(
                    status="failed", error=type(error).__name__, updated_at=now())
        else:
            result["queue_wait_ms"] = self._jobs[job_id]["queue_wait_ms"]
            with self._lock:
                self._jobs[job_id].update(status="completed", result=result, updated_at=now())
        finally:
            with self._lock:
                self._active.pop(key, None)
                self._jobs[job_id]["execution_ms"] = round((time.perf_counter() - started) * 1000, 2)
                self._slots.release()
                for old_id in list(self._jobs):
                    if len(self._jobs) <= self.history_limit:
                        break
                    if self._jobs[old_id]["status"] in {"completed", "failed"}:
                        self._jobs.pop(old_id)
                        self._submitted.pop(old_id, None)

    def get(self, job_id: str) -> dict:
        """Read a job status; results include the associated customer session."""
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            return dict(self._jobs[job_id])

    def stats(self) -> dict:
        """Report queue limits and current utilization."""
        with self._lock:
            return {
                "workers": self.workers, "capacity": self.capacity,
                "queued": sum(job["status"] == "queued" for job in self._jobs.values()),
                "running": sum(job["status"] == "running" for job in self._jobs.values()),
            }

    def close(self) -> None:
        """Drain accepted work before closing; no orphaned inference threads."""
        self._pool.shutdown(wait=True)
