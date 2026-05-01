"""TranscribeJob + TranscribeJobManager.

Same lock + ThreadPoolExecutor + JSON persistence pattern as jobs.py.
Operates on parent media jobs by id. Each TranscribeJob has its own
lifecycle independent of the media Job's status.
"""
from __future__ import annotations
import enum
import json
import os
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable


class TranscribeStatus(str, enum.Enum):
    QUEUED      = "queued"
    RUNNING     = "running"
    DONE        = "done"
    ERROR       = "error"
    CANCELLED   = "cancelled"


@dataclass
class TranscribeJob:
    id: str
    parent_job_id: str
    model_used: str
    status: TranscribeStatus = TranscribeStatus.QUEUED
    progress_pct: int = 0
    started_at: float = field(default_factory=time.monotonic)
    duration_seconds: float = 0.0
    language_detected: str = ""
    error_category: str | None = None
    error_message: str | None = None
    # Not persisted:
    process_handle: object | None = None
    _cancel_flag: bool = False


_PERSISTENT_FIELDS = {
    "id", "parent_job_id", "status", "progress_pct", "started_at",
    "duration_seconds", "model_used", "language_detected",
    "error_category", "error_message",
}


class TranscribeJobManager:
    def __init__(self, *, max_workers: int = 1, store_path: object = None):
        self.max_workers = max_workers
        self._jobs: dict[str, TranscribeJob] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._store_path = Path(store_path) if store_path else None
        if self._store_path is not None:
            self._load_from_store()

    # ----- persistence ---------------------------------------------------

    def _load_from_store(self) -> None:
        if not self._store_path.exists():
            return
        try:
            data = json.loads(self._store_path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        if data.get("schema_version") != 1:
            return
        for jid, raw in (data.get("jobs") or {}).items():
            try:
                status_str = raw.get("status", "queued")
                # Downgrade running → error on restart (whisper has no resume)
                if status_str in ("running", "queued"):
                    raw["status"] = TranscribeStatus.ERROR.value
                    raw["error_category"] = "server_restart"
                    raw["error_message"] = "transcribe interrupted by server restart"
                job = TranscribeJob(
                    id=raw["id"],
                    parent_job_id=raw["parent_job_id"],
                    model_used=raw.get("model_used", ""),
                    status=TranscribeStatus(raw["status"]),
                    progress_pct=raw.get("progress_pct", 0),
                    started_at=raw.get("started_at", 0.0),
                    duration_seconds=raw.get("duration_seconds", 0.0),
                    language_detected=raw.get("language_detected", ""),
                    error_category=raw.get("error_category"),
                    error_message=raw.get("error_message"),
                )
                self._jobs[jid] = job
            except (KeyError, ValueError):
                continue

    def _persist(self) -> None:
        if self._store_path is None:
            return
        try:
            payload = {
                "schema_version": 1,
                "jobs": {
                    jid: {k: v for k, v in asdict(j).items() if k in _PERSISTENT_FIELDS}
                    for jid, j in self._jobs.items()
                },
            }
            # asdict converts enum to "queued" via str enum; ensure status is a string
            for jid, raw in payload["jobs"].items():
                raw["status"] = self._jobs[jid].status.value

            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".tj.", dir=str(self._store_path.parent))
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(payload, f, indent=2)
                os.replace(tmp, self._store_path)
            except Exception:
                try: os.unlink(tmp)
                except OSError: pass
                raise
        except Exception:
            pass  # persistence failure shouldn't crash a transcribe

    # ----- lifecycle -----------------------------------------------------

    def submit(self, *, parent_job_id: str, model_path: str,
               target: Callable[[TranscribeJob], None]) -> str:
        jid = uuid.uuid4().hex[:10]
        model_name = Path(model_path).name if model_path else ""
        job = TranscribeJob(id=jid, parent_job_id=parent_job_id, model_used=model_name)
        with self._lock:
            self._jobs[jid] = job
        self._persist()

        def _run():
            try:
                with self._lock:
                    job.status = TranscribeStatus.RUNNING
                self._persist()
                target(job, model_path=model_path)
                with self._lock:
                    if job.status not in {TranscribeStatus.CANCELLED, TranscribeStatus.ERROR}:
                        job.status = TranscribeStatus.DONE
                        job.progress_pct = 100
                self._persist()
            except Exception as e:
                with self._lock:
                    job.status = TranscribeStatus.ERROR
                    job.error_category = job.error_category or "unknown"
                    job.error_message = job.error_message or str(e)
                self._persist()

        self._executor.submit(_run)
        return jid

    def cancel(self, jid: str) -> bool:
        with self._lock:
            j = self._jobs.get(jid)
            if j is None:
                return False
            if j.status in {TranscribeStatus.DONE, TranscribeStatus.ERROR, TranscribeStatus.CANCELLED}:
                return False
            j._cancel_flag = True
            j.status = TranscribeStatus.CANCELLED
            proc = j.process_handle
        if proc is not None and hasattr(proc, "kill"):
            try: proc.kill()
            except Exception: pass
        self._persist()
        return True

    def dismiss(self, jid: str) -> bool:
        with self._lock:
            j = self._jobs.get(jid)
            if j is None:
                return False
            if j.status not in {TranscribeStatus.DONE, TranscribeStatus.ERROR, TranscribeStatus.CANCELLED}:
                return False
            del self._jobs[jid]
        self._persist()
        return True

    def get(self, jid: str) -> TranscribeJob | None:
        with self._lock:
            return self._jobs.get(jid)

    def get_by_parent(self, parent_job_id: str) -> TranscribeJob | None:
        """Return the most recent TranscribeJob for this parent, if any."""
        with self._lock:
            matching = [j for j in self._jobs.values() if j.parent_job_id == parent_job_id]
        if not matching:
            return None
        return max(matching, key=lambda j: j.started_at)

    def snapshot_jobs(self) -> list[TranscribeJob]:
        with self._lock:
            return list(self._jobs.values())

    def update_progress(self, jid: str, pct: int) -> None:
        with self._lock:
            j = self._jobs.get(jid)
            if j is not None and j.status == TranscribeStatus.RUNNING:
                j.progress_pct = max(0, min(100, int(pct)))

    def shutdown(self, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait)
