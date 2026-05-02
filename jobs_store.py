"""Atomic JSON persistence for the Job dict.

Single-writer model: only the Flask process writes; readers get whatever was
last fully written. Atomic via os.replace — partial writes never replace the
canonical file.

The schema is versioned; future migrations can branch on `version`. Loaders
silently return an empty dict on malformed JSON, missing file, or unknown
version. We never want a corrupted store to crash the app.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

from jobs import Job, JobStatus


SCHEMA_VERSION = 1

# Persistent fields only. Transient runtime state (Popen handle, _was_paused
# flag, internal monotonic timestamps) stays in memory.
_PERSISTENT_FIELDS = (
    "id", "url", "title", "status", "thumbnail",
    "file_path", "filename", "error_category", "error_message",
    "downloaded_bytes", "total_bytes", "speed", "eta",
    "fragment_index", "fragment_count",
    "format_choice", "format_id", "out_template",
    "auto_transcribe",
)


def _job_to_dict(job: Job) -> dict:
    out = {}
    for field_name in _PERSISTENT_FIELDS:
        value = getattr(job, field_name)
        if isinstance(value, JobStatus):
            value = value.value
        out[field_name] = value
    return out


def _job_from_dict(data: dict) -> Job:
    status = JobStatus(data.get("status", JobStatus.QUEUED.value))
    return Job(
        id=data["id"],
        url=data["url"],
        title=data.get("title", ""),
        status=status,
        thumbnail=data.get("thumbnail", "") or "",
        file_path=data.get("file_path"),
        filename=data.get("filename"),
        error_category=data.get("error_category"),
        error_message=data.get("error_message"),
        downloaded_bytes=int(data.get("downloaded_bytes") or 0),
        total_bytes=int(data.get("total_bytes") or 0),
        speed=float(data.get("speed") or 0.0),
        eta=int(data.get("eta") or 0),
        fragment_index=int(data.get("fragment_index") or 0),
        fragment_count=int(data.get("fragment_count") or 0),
        format_choice=data.get("format_choice") or "video",
        format_id=data.get("format_id"),
        out_template=data.get("out_template") or "",
        auto_transcribe=bool(data.get("auto_transcribe") or False),
    )


def dump_jobs(jobs: dict[str, Job]) -> dict:
    return {
        "version": SCHEMA_VERSION,
        "jobs": [_job_to_dict(j) for j in jobs.values()],
    }


def persist_atomic(jobs: dict[str, Job], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(dump_jobs(jobs), indent=2))
        os.replace(tmp, path)
    except Exception:
        # If the temp write fails, leave the existing file intact and clean up.
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def load_jobs(path: Path) -> dict[str, Job]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    if raw.get("version") != SCHEMA_VERSION:
        return {}
    out: dict[str, Job] = {}
    for entry in raw.get("jobs", []) or []:
        try:
            j = _job_from_dict(entry)
            out[j.id] = j
        except (KeyError, ValueError, TypeError):
            continue  # skip individually broken entries; don't poison the rest
    return out
