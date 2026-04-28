from __future__ import annotations
import enum
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from queue import Full
from typing import Callable


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class Job:
    id: str
    url: str
    title: str
    status: JobStatus = JobStatus.QUEUED
    file_path: str | None = None
    filename: str | None = None
    error_category: str | None = None
    error_message: str | None = None
    process: object | None = None  # subprocess.Popen, set by runner if it wants kill support
    created_at: float = field(default_factory=time.monotonic)
    last_accessed: float = field(default_factory=time.monotonic)


class JobManager:
    def __init__(self, *, max_workers: int = 4, ttl_seconds: int = 3600, queue_size: int | None = None):
        self.max_workers = max_workers
        self.ttl_seconds = ttl_seconds
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._inflight = 0
        self._queue_size = queue_size  # None = unlimited; 0 = no queue, must be free worker

    def submit(self, *, target: Callable[[Job], None], title: str, url: str) -> str:
        job_id = uuid.uuid4().hex[:10]
        job = Job(id=job_id, url=url, title=title, status=JobStatus.QUEUED)
        with self._lock:
            if self._queue_size == 0 and self._inflight >= self.max_workers:
                raise RuntimeError("pool full")
            self._jobs[job_id] = job
            self._inflight += 1

        def _run():
            time.sleep(0.001)  # Let main thread return from submit() first
            try:
                with self._lock:
                    job.status = JobStatus.DOWNLOADING
                target(job)
                with self._lock:
                    if job.status not in {JobStatus.ERROR, JobStatus.CANCELLED}:
                        job.status = JobStatus.DONE
            except Exception as e:
                with self._lock:
                    job.status = JobStatus.ERROR
                    job.error_category = job.error_category or "unknown"
                    job.error_message = job.error_message or str(e)
            finally:
                with self._lock:
                    self._inflight -= 1

        self._executor.submit(_run)
        return job_id

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            j = self._jobs.get(job_id)
            if j is not None:
                j.last_accessed = time.monotonic()
            return j

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            proc = job.process
            if job.status in {JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELLED}:
                # If finished, treat cancel as cleanup.
                if job.file_path and os.path.exists(job.file_path):
                    try:
                        os.remove(job.file_path)
                    except OSError:
                        pass
                job.status = JobStatus.CANCELLED
                return True
            job.status = JobStatus.CANCELLED
        # Outside lock: kill the subprocess if any.
        if proc is not None and hasattr(proc, "kill"):
            try:
                proc.kill()
            except Exception:
                pass
        return True

    def sweep(self) -> int:
        """Drop done/errored/cancelled jobs older than ttl_seconds. Returns count removed."""
        cutoff = time.monotonic() - self.ttl_seconds
        removed = 0
        with self._lock:
            to_remove = [
                jid for jid, j in self._jobs.items()
                if j.status in {JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELLED}
                and j.last_accessed <= cutoff
            ]
            for jid in to_remove:
                job = self._jobs.pop(jid)
                if job.file_path and os.path.exists(job.file_path):
                    try:
                        os.remove(job.file_path)
                    except OSError:
                        pass
                removed += 1
        return removed

    def start_sweeper(self, interval_seconds: int = 300) -> None:
        def loop():
            while True:
                time.sleep(interval_seconds)
                try:
                    self.sweep()
                except Exception:
                    pass
        t = threading.Thread(target=loop, daemon=True, name="trove-sweeper")
        t.start()

    def shutdown(self, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait)
