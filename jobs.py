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
    PAUSED = "paused"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class Job:
    id: str
    url: str
    title: str
    status: JobStatus = JobStatus.QUEUED
    thumbnail: str = ""
    file_path: str | None = None
    filename: str | None = None
    error_category: str | None = None
    error_message: str | None = None
    process: object | None = None  # subprocess.Popen, set by runner if it wants kill support
    created_at: float = field(default_factory=time.monotonic)
    last_accessed: float = field(default_factory=time.monotonic)
    # Progress (populated by runner during DOWNLOADING)
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed: float = 0.0  # bytes/sec
    eta: int = 0  # seconds remaining
    # HLS / fragmented downloads expose fragment counts even when total_bytes is unknown.
    fragment_index: int = 0
    fragment_count: int = 0
    # Resume args — captured at submit time so a paused job can be re-run after restart
    format_choice: str = "video"
    format_id: str | None = None
    out_template: str = ""
    # Transient flag set by JobManager.pause() before the process is killed,
    # so runner._cleanup_glob() can be skipped (preserves .part files).
    _was_paused: bool = False


class JobManager:
    def __init__(
        self,
        *,
        max_workers: int = 4,
        ttl_seconds: int = 3600,
        queue_size: int | None = None,
        store_path: object = None,  # Path or None; None disables persistence
    ):
        from pathlib import Path  # local import to avoid module-level coupling
        self.max_workers = max_workers
        self.ttl_seconds = ttl_seconds
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._inflight = 0
        self._queue_size = queue_size
        self._store_path = Path(store_path) if store_path else None
        if self._store_path is not None:
            self._load_from_store()

    def _load_from_store(self) -> None:
        from jobs_store import load_jobs
        loaded = load_jobs(self._store_path)
        for jid, job in loaded.items():
            # Downgrade rules per design §4.2:
            # DOWNLOADING / QUEUED → PAUSED (interrupted by restart, no live thunk)
            # CANCELLED dropped (no point keeping)
            # DONE / ERROR / PAUSED kept as-is
            if job.status in (JobStatus.DOWNLOADING, JobStatus.QUEUED):
                job.status = JobStatus.PAUSED
            elif job.status == JobStatus.CANCELLED:
                continue
            self._jobs[jid] = job

    def _persist(self) -> None:
        if self._store_path is None:
            return
        try:
            from jobs_store import persist_atomic
            persist_atomic(self._jobs, self._store_path)
        except Exception:
            # Persistence failure shouldn't crash a download.
            pass

    def submit(self, *, target: Callable[[Job], None], title: str, url: str) -> str:
        job_id = uuid.uuid4().hex[:10]
        job = Job(id=job_id, url=url, title=title, status=JobStatus.QUEUED)
        with self._lock:
            if self._queue_size == 0 and self._inflight >= self.max_workers:
                raise RuntimeError("pool full")
            self._jobs[job_id] = job
            self._inflight += 1
        self._persist()

        def _run():
            time.sleep(0.001)
            try:
                with self._lock:
                    job.status = JobStatus.DOWNLOADING
                self._persist()
                target(job)
                with self._lock:
                    if job.status == JobStatus.PAUSED and job.file_path:
                        # Pause raced runner success — runner already wrote a real file.
                        job.status = JobStatus.DONE
                        job._was_paused = False
                    elif job.status not in {JobStatus.ERROR, JobStatus.CANCELLED, JobStatus.PAUSED}:
                        job.status = JobStatus.DONE
                self._persist()
            except Exception as e:
                with self._lock:
                    job.status = JobStatus.ERROR
                    job.error_category = job.error_category or "unknown"
                    job.error_message = job.error_message or str(e)
                self._persist()
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

    def snapshot_jobs(self) -> list[Job]:
        """Return a list copy of the current jobs in insertion order.

        Returns live Job references — the caller may observe torn reads of
        `downloaded_bytes` / `total_bytes` etc. if a worker thread mutates
        them mid-render. That's cosmetic (the next 2s status poll resolves
        it). Used for rendering persisted jobs on page reload.
        """
        with self._lock:
            return list(self._jobs.values())

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            proc = job.process
            out_template = job.out_template
            if job.status in {JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELLED}:
                if job.file_path and os.path.exists(job.file_path):
                    try:
                        os.remove(job.file_path)
                    except OSError:
                        pass
                job.status = JobStatus.CANCELLED
                self._persist()
                return True
            job.status = JobStatus.CANCELLED
        if proc is not None and hasattr(proc, "kill"):
            try:
                proc.kill()
            except Exception:
                pass
        if out_template:
            try:
                from runner import _cleanup_glob
                _cleanup_glob(out_template)
            except Exception:
                pass
        self._persist()
        return True

    def dismiss(self, job_id: str) -> bool:
        """Remove a terminal-state job from the queue and delete its file.

        Symmetric with the TTL sweep but user-triggered. Refuses non-terminal
        jobs (caller should cancel or pause first to avoid orphaning a running
        yt-dlp subprocess).
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status not in {JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELLED}:
                return False
            file_path = job.file_path
            del self._jobs[job_id]
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
        self._persist()
        return True

    def pause(self, job_id: str) -> bool:
        """Pause an active or queued job. Keeps .part files for resume.

        Returns True if the job is now paused (or was already paused).
        Returns False if the job is unknown or in a terminal state.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status in {JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELLED}:
                return False
            if job.status == JobStatus.PAUSED:
                return True  # idempotent
            proc = job.process
            job._was_paused = True       # tell runner: skip cleanup
            job.status = JobStatus.PAUSED
        # Outside lock: kill the subprocess if any.
        if proc is not None and hasattr(proc, "kill"):
            try:
                proc.kill()
            except Exception:
                pass
        self._persist()
        return True

    def resume(self, job_id: str, *, target: Callable[[Job], None]) -> bool:
        """Resume a paused job. Re-submits the work target to the executor.

        The caller (app.py) is responsible for constructing the target closure
        from the persisted Job.format_choice / format_id / out_template /
        url / title etc. — this method just re-runs whatever target the
        caller supplies.

        Returns True if the job is now downloading.
        Returns False if the job is unknown or in a terminal state.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status in {JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELLED}:
                return False
            if job.status == JobStatus.DOWNLOADING:
                return True  # idempotent — already running
            job.status = JobStatus.DOWNLOADING
            job._was_paused = False
            self._inflight += 1
        self._persist()

        def _run():
            try:
                target(job)
                with self._lock:
                    if job.status == JobStatus.PAUSED and job.file_path:
                        # Pause raced runner success — runner already wrote a real file.
                        job.status = JobStatus.DONE
                        job._was_paused = False
                    elif job.status not in {JobStatus.ERROR, JobStatus.CANCELLED, JobStatus.PAUSED}:
                        job.status = JobStatus.DONE
                self._persist()
            except Exception as e:
                with self._lock:
                    job.status = JobStatus.ERROR
                    job.error_category = job.error_category or "unknown"
                    job.error_message = job.error_message or str(e)
                self._persist()
            finally:
                with self._lock:
                    self._inflight -= 1

        self._executor.submit(_run)
        return True

    def sweep(self, *, keep_predicate: Callable[[Job], bool] | None = None) -> int:
        """Drop terminal jobs whose last_accessed is older than ttl_seconds.

        ``keep_predicate(job) -> bool`` (optional): when supplied and it
        returns True for a job that would otherwise be swept, the job is
        retained AND its ``last_accessed`` is refreshed so it doesn't
        immediately re-qualify for sweep on the next pass.

        This hook exists so the app can preserve parent media jobs that
        still have a completed transcribe child — without it, the TTL
        sweep would silently 404 every transcript page after one idle
        hour and unlink the source media that the transcript's <video>
        element points at.
        """
        cutoff = time.monotonic() - self.ttl_seconds
        removed = 0
        with self._lock:
            kept_ids: list[str] = []
            to_remove: list[str] = []
            for jid, j in self._jobs.items():
                if j.status not in {JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELLED}:
                    continue
                if j.last_accessed > cutoff:
                    continue
                if keep_predicate is not None:
                    try:
                        if keep_predicate(j):
                            kept_ids.append(jid)
                            continue
                    except Exception:
                        # A buggy predicate must not destroy a real job.
                        kept_ids.append(jid)
                        continue
                to_remove.append(jid)
            for jid in to_remove:
                job = self._jobs.pop(jid)
                if job.file_path and os.path.exists(job.file_path):
                    try:
                        os.remove(job.file_path)
                    except OSError:
                        pass
                removed += 1
            now = time.monotonic()
            for jid in kept_ids:
                # Bump last_accessed so we don't re-evaluate on every sweep.
                self._jobs[jid].last_accessed = now
        if removed:
            self._persist()
        return removed

    def start_sweeper(
        self,
        interval_seconds: int = 300,
        *,
        keep_predicate: Callable[[Job], bool] | None = None,
    ) -> None:
        def loop():
            while True:
                time.sleep(interval_seconds)
                try:
                    self.sweep(keep_predicate=keep_predicate)
                except Exception:
                    pass
        t = threading.Thread(target=loop, daemon=True, name="trove-sweeper")
        t.start()

    def shutdown(self, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait)
