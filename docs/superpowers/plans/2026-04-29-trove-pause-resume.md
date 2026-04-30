# Trove — Speed flags + Pause/Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--concurrent-fragments` for ~3× faster YouTube/HLS downloads, plus IDM-style pause/resume that survives Trove restarts.

**Architecture:** Reuses yt-dlp's built-in `--concurrent-fragments` and `--continue` flags rather than rolling a custom segmenting engine. Job state persists to `downloads/jobs.json` via atomic write. Pause keeps `.part` files; cancel deletes them; resume relaunches yt-dlp which picks up the partial via `--continue` (default-on).

**Tech Stack:** Python 3.12 · Flask · yt-dlp · htmx 2 · pytest

**Spec:** `docs/superpowers/specs/2026-04-29-trove-pause-resume-design.md` — read before starting.

---

## Setup notes

- Work on a feature branch (`speed-pause-resume` recommended). The repo `main` should stay green throughout. Each task ends in a discrete commit so any single step can be reverted cleanly.
- Tests live in `tests/`. Run with `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/`. Existing test count baseline: **63 passing**.
- Dev loop: keep `./trove.sh` in one terminal and `localhost:8899` open. The Tailwind CLI watches `styles/input.css`. Hot-reload after every UI change.

## File structure

| File | Status | Purpose |
|---|---|---|
| `runner.py` | modify | Add `--concurrent-fragments` + retries flags; honor `Job._was_paused` to skip `_cleanup_glob()` |
| `jobs.py` | modify | New `PAUSED` status; new `Job` fields (`format_choice`, `format_id`, `out_template`, `_was_paused`); `pause()` and `resume()` methods on `JobManager`; persistence hook |
| `jobs_store.py` | **CREATE** | Atomic JSON serialize/deserialize for `Job` dict |
| `app.py` | modify | New `/api/job/<id>/pause` and `/api/job/<id>/resume` endpoints; load store on startup; `_enqueue_download` writes `out_template` + format args to Job for resume |
| `templates/base.html` | modify | `beforeunload` sendBeacon `/pause` instead of `/cancel`; `refreshActiveJobs` selector includes `paused` |
| `templates/partials/card.html` | modify | New `.clip.is-paused` Jinja branch; pause+cancel buttons inside `.is-downloading` |
| `styles/input.css` | modify | `.clip.is-paused`, `.clip-pause`, `.clip-resume`, `.clip-cancel` rules |
| `tests/test_runner.py` | modify | Test for new argv flags |
| `tests/test_jobs.py` | modify | Tests for `pause()`, `resume()`, transition rules, startup downgrade |
| `tests/test_jobs_store.py` | **CREATE** | Round-trip serialize/deserialize, atomic write, malformed JSON, version mismatch |
| `tests/test_endpoints.py` | modify | Tests for `/pause` and `/resume` endpoints |

---

## Task 1: Speed flags (ships independently)

**Files:**
- Modify: `runner.py:36-58` (build_download_argv)
- Modify: `tests/test_runner.py` (add flag-coverage test)

- [ ] **Step 1.1: Write the failing test for new flags**

Append to `tests/test_runner.py`:

```python
def test_download_argv_includes_concurrent_fragments():
    argv = build_download_argv(
        url="https://example.com/v",
        out_template="/tmp/x.%(ext)s",
        format_choice="video",
        format_id=None,
    )
    assert "--concurrent-fragments" in argv
    n_idx = argv.index("--concurrent-fragments")
    assert argv[n_idx + 1].isdigit()
    assert int(argv[n_idx + 1]) >= 1


def test_download_argv_includes_retry_flags():
    argv = build_download_argv(
        url="https://example.com/v",
        out_template="/tmp/x.%(ext)s",
        format_choice="video",
        format_id=None,
    )
    assert "--retries" in argv
    assert "--fragment-retries" in argv
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_runner.py::test_download_argv_includes_concurrent_fragments tests/test_runner.py::test_download_argv_includes_retry_flags -v`

Expected: FAIL — "assert '--concurrent-fragments' in argv".

- [ ] **Step 1.3: Add flags to build_download_argv**

In `runner.py`, locate the `build_download_argv` function and modify the initial argv list. Replace:

```python
    argv: list[str] = [
        "yt-dlp",
        "--no-playlist",
        "-o", out_template,
        *_cookie_args(),
    ]
```

with:

```python
    concurrent_fragments = max(1, min(32, int(os.environ.get("TROVE_CONCURRENT_FRAGMENTS", "4"))))
    argv: list[str] = [
        "yt-dlp",
        "--no-playlist",
        "--concurrent-fragments", str(concurrent_fragments),
        "--retries", "5",
        "--fragment-retries", "10",
        "-o", out_template,
        *_cookie_args(),
    ]
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_runner.py -v`

Expected: PASS — all runner tests including the new two.

- [ ] **Step 1.5: Run full test suite**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/`

Expected: 65 passed (63 baseline + 2 new).

- [ ] **Step 1.6: Commit**

```bash
git add runner.py tests/test_runner.py
git commit -m "$(cat <<'EOF'
feat(runner): add --concurrent-fragments + retry flags

Default --concurrent-fragments 4 (env-overridable via
TROVE_CONCURRENT_FRAGMENTS, clamped to [1,32]). Adds --retries 5 and
--fragment-retries 10. Speeds up YouTube/HLS downloads ~3×.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add `PAUSED` status + new `Job` fields

**Files:**
- Modify: `jobs.py:13-42`
- Modify: `tests/test_jobs.py`

- [ ] **Step 2.1: Write the failing test**

Append to `tests/test_jobs.py`:

```python
def test_job_status_includes_paused():
    assert JobStatus.PAUSED.value == "paused"


def test_job_dataclass_has_resume_fields():
    j = Job(id="x", url="https://e.com", title="t")
    assert hasattr(j, "format_choice")
    assert hasattr(j, "format_id")
    assert hasattr(j, "out_template")
    assert j.format_choice == "video"
    assert j.format_id is None
    assert j.out_template == ""
    assert j._was_paused is False
```

- [ ] **Step 2.2: Run test to verify it fails**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_jobs.py::test_job_status_includes_paused tests/test_jobs.py::test_job_dataclass_has_resume_fields -v`

Expected: FAIL — `'JobStatus' has no attribute 'PAUSED'`.

- [ ] **Step 2.3: Add PAUSED + new fields**

In `jobs.py`, replace lines 13-18 (the `JobStatus` enum) with:

```python
class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"
```

Then in the `Job` dataclass (lines 21-42), append the new fields after `fragment_count: int = 0`:

```python
    # Resume args — captured at submit time so a paused job can be re-run after restart
    format_choice: str = "video"
    format_id: str | None = None
    out_template: str = ""
    # Transient flag set by JobManager.pause() before the process is killed,
    # so runner._cleanup_glob() can be skipped (preserves .part files).
    _was_paused: bool = False
```

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_jobs.py -v`

Expected: All `test_jobs.py` tests pass including the two new ones.

- [ ] **Step 2.5: Commit**

```bash
git add jobs.py tests/test_jobs.py
git commit -m "$(cat <<'EOF'
feat(jobs): add PAUSED status + resume_args + _was_paused fields

JobStatus.PAUSED for the new state. Job gains format_choice,
format_id, out_template (needed to reconstruct work thunk on resume)
plus a transient _was_paused flag that the runner checks to skip
.part cleanup when the user paused vs cancelled.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Build `JobStore` (TDD)

**Files:**
- Create: `jobs_store.py`
- Create: `tests/test_jobs_store.py`

- [ ] **Step 3.1: Write the failing tests**

Create `tests/test_jobs_store.py`:

```python
import json
from pathlib import Path
import pytest

from jobs import Job, JobStatus
from jobs_store import dump_jobs, load_jobs, persist_atomic


def test_dump_and_load_round_trip(tmp_path):
    jobs_in = {
        "abc": Job(
            id="abc", url="https://example.com/v", title="Hello",
            status=JobStatus.PAUSED,
            thumbnail="https://example.com/t.jpg",
            downloaded_bytes=1024, total_bytes=4096,
            fragment_index=2, fragment_count=8,
            format_choice="video", format_id="137",
            out_template=str(tmp_path / "abc.%(ext)s"),
            file_path=None, filename=None,
        ),
    }
    path = tmp_path / "jobs.json"
    persist_atomic(jobs_in, path)
    assert path.exists()

    jobs_out = load_jobs(path)
    j = jobs_out["abc"]
    assert j.url == "https://example.com/v"
    assert j.title == "Hello"
    assert j.status == JobStatus.PAUSED
    assert j.downloaded_bytes == 1024
    assert j.fragment_count == 8
    assert j.format_id == "137"
    assert j.out_template.endswith("abc.%(ext)s")


def test_load_returns_empty_dict_when_file_missing(tmp_path):
    assert load_jobs(tmp_path / "nope.json") == {}


def test_load_tolerates_malformed_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not valid json")
    assert load_jobs(path) == {}


def test_load_tolerates_unknown_version(tmp_path):
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"version": 999, "jobs": []}))
    assert load_jobs(path) == {}


def test_persist_atomic_uses_tempfile_then_rename(tmp_path):
    """If write fails partway, the existing file should still be intact."""
    path = tmp_path / "jobs.json"
    jobs1 = {"a": Job(id="a", url="https://e.com/1", title="first")}
    persist_atomic(jobs1, path)

    # Atomic — temp file should not linger
    assert not (tmp_path / "jobs.json.tmp").exists()
    assert path.exists()

    # Rewrite — should overwrite, not duplicate
    jobs2 = {"b": Job(id="b", url="https://e.com/2", title="second")}
    persist_atomic(jobs2, path)
    loaded = load_jobs(path)
    assert "a" not in loaded
    assert "b" in loaded


def test_dump_omits_transient_fields(tmp_path):
    """The Popen handle and _was_paused flag should NOT serialize."""
    j = Job(id="x", url="https://e.com", title="t", status=JobStatus.DOWNLOADING)
    j.process = object()  # would not be JSON-serializable
    j._was_paused = True
    path = tmp_path / "jobs.json"
    persist_atomic({"x": j}, path)
    raw = json.loads(path.read_text())
    serialized = raw["jobs"][0]
    assert "process" not in serialized
    assert "_was_paused" not in serialized


def test_dump_serializes_all_persistent_fields(tmp_path):
    j = Job(
        id="x", url="https://e.com/v", title="t",
        status=JobStatus.PAUSED,
        thumbnail="https://e.com/t.jpg",
        file_path="/tmp/x.mp4", filename="x.mp4",
        downloaded_bytes=10, total_bytes=100,
        speed=1.5, eta=42,
        fragment_index=3, fragment_count=10,
        format_choice="audio", format_id=None,
        out_template="/tmp/x.%(ext)s",
        error_category=None, error_message=None,
    )
    path = tmp_path / "jobs.json"
    persist_atomic({"x": j}, path)
    raw = json.loads(path.read_text())
    s = raw["jobs"][0]
    assert s["url"] == "https://e.com/v"
    assert s["status"] == "paused"
    assert s["downloaded_bytes"] == 10
    assert s["fragment_count"] == 10
    assert s["format_choice"] == "audio"
    assert s["out_template"] == "/tmp/x.%(ext)s"
    assert s["filename"] == "x.mp4"
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_jobs_store.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'jobs_store'`.

- [ ] **Step 3.3: Implement jobs_store.py**

Create `/Users/kaivan108icloud.com/Downloads/trove/jobs_store.py`:

```python
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
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_jobs_store.py -v`

Expected: All 7 tests pass.

- [ ] **Step 3.5: Commit**

```bash
git add jobs_store.py tests/test_jobs_store.py
git commit -m "$(cat <<'EOF'
feat(jobs): add JobStore for atomic JSON persistence

Single-writer model writes the in-memory job dict to downloads/jobs.json
via tempfile + os.replace. Loader tolerates missing file, malformed
JSON, and version mismatch (returns {} in all error cases — never
crashes the app on a corrupt store). Persistent fields whitelisted;
Popen handle and transient flags excluded.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Wire `JobStore` into `JobManager`

**Files:**
- Modify: `jobs.py:45-148` (JobManager class)
- Modify: `tests/test_jobs.py`

- [ ] **Step 4.1: Write the failing tests**

Append to `tests/test_jobs.py`:

```python
def test_jobmanager_persists_on_state_change(tmp_path):
    from jobs_store import load_jobs
    store_path = tmp_path / "jobs.json"
    jm = JobManager(max_workers=1, ttl_seconds=60, store_path=store_path)

    jid = jm.submit(target=lambda j: None, title="hi", url="https://x")
    # Wait for the worker to finish
    for _ in range(50):
        if jm.get(jid).status == JobStatus.DONE:
            break
        time.sleep(0.05)

    # The store file should exist and contain the job
    assert store_path.exists()
    loaded = load_jobs(store_path)
    assert jid in loaded
    assert loaded[jid].status == JobStatus.DONE
    jm.shutdown()


def test_jobmanager_load_downgrades_downloading_to_paused(tmp_path):
    """After a crash/restart, jobs left in DOWNLOADING are reset to PAUSED."""
    from jobs_store import persist_atomic
    store_path = tmp_path / "jobs.json"
    job = Job(
        id="abc", url="https://e.com/v", title="t",
        status=JobStatus.DOWNLOADING,
        out_template=str(tmp_path / "abc.%(ext)s"),
    )
    persist_atomic({"abc": job}, store_path)

    jm = JobManager(max_workers=1, ttl_seconds=60, store_path=store_path)
    j = jm.get("abc")
    assert j is not None
    assert j.status == JobStatus.PAUSED  # downgraded from DOWNLOADING
    jm.shutdown()


def test_jobmanager_load_downgrades_queued_to_paused(tmp_path):
    """QUEUED jobs at startup also become PAUSED — their work thunk is gone."""
    from jobs_store import persist_atomic
    store_path = tmp_path / "jobs.json"
    job = Job(
        id="abc", url="https://e.com/v", title="t",
        status=JobStatus.QUEUED,
        out_template=str(tmp_path / "abc.%(ext)s"),
    )
    persist_atomic({"abc": job}, store_path)

    jm = JobManager(max_workers=1, ttl_seconds=60, store_path=store_path)
    assert jm.get("abc").status == JobStatus.PAUSED
    jm.shutdown()


def test_jobmanager_load_drops_cancelled(tmp_path):
    from jobs_store import persist_atomic
    store_path = tmp_path / "jobs.json"
    persist_atomic(
        {"x": Job(id="x", url="https://e.com", title="t", status=JobStatus.CANCELLED)},
        store_path,
    )
    jm = JobManager(max_workers=1, ttl_seconds=60, store_path=store_path)
    assert jm.get("x") is None
    jm.shutdown()


def test_jobmanager_load_keeps_done_and_error(tmp_path):
    from jobs_store import persist_atomic
    store_path = tmp_path / "jobs.json"
    persist_atomic(
        {
            "d": Job(id="d", url="https://e.com/1", title="d", status=JobStatus.DONE),
            "e": Job(id="e", url="https://e.com/2", title="e", status=JobStatus.ERROR),
        },
        store_path,
    )
    jm = JobManager(max_workers=1, ttl_seconds=60, store_path=store_path)
    assert jm.get("d").status == JobStatus.DONE
    assert jm.get("e").status == JobStatus.ERROR
    jm.shutdown()
```

- [ ] **Step 4.2: Run tests to verify they fail**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_jobs.py::test_jobmanager_persists_on_state_change tests/test_jobs.py::test_jobmanager_load_downgrades_downloading_to_paused -v`

Expected: FAIL — `JobManager() got unexpected keyword argument 'store_path'`.

- [ ] **Step 4.3: Wire JobStore into JobManager**

In `jobs.py`, modify the `JobManager.__init__` (line 46) and add load + persist hooks. Replace the entire `JobManager` class with:

```python
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
                    if job.status not in {JobStatus.ERROR, JobStatus.CANCELLED, JobStatus.PAUSED}:
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

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            proc = job.process
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
        self._persist()
        return True

    def sweep(self) -> int:
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
        if removed:
            self._persist()
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
```

- [ ] **Step 4.4: Run tests to verify they pass**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_jobs.py -v`

Expected: All `test_jobs.py` tests pass including the 5 new ones.

- [ ] **Step 4.5: Commit**

```bash
git add jobs.py tests/test_jobs.py
git commit -m "$(cat <<'EOF'
feat(jobs): wire JobStore into JobManager

JobManager(store_path=...) loads on init and persists after every
state change. On startup, DOWNLOADING and QUEUED jobs downgrade to
PAUSED (interrupted by restart). CANCELLED jobs are dropped. DONE,
ERROR, and PAUSED keep their state. Persistence failures are
swallowed — never crash a download.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `JobManager.pause()` method

**Files:**
- Modify: `jobs.py` (JobManager class)
- Modify: `tests/test_jobs.py`

- [ ] **Step 5.1: Write the failing tests**

Append to `tests/test_jobs.py`:

```python
def test_pause_marks_paused_and_kills_process():
    jm = JobManager(max_workers=1, ttl_seconds=60)
    jid = jm.submit(target=lambda j: time.sleep(2), title="t", url="https://x")
    # Inject a fake process so we can verify it gets killed
    fake = type("P", (), {"killed": False, "kill": lambda self: setattr(self, "killed", True)})()
    jm.get(jid).process = fake

    assert jm.pause(jid) is True
    assert jm.get(jid).status == JobStatus.PAUSED
    assert jm.get(jid)._was_paused is True
    assert fake.killed is True
    jm.shutdown()


def test_pause_idempotent_on_already_paused():
    jm = JobManager(max_workers=1, ttl_seconds=60)
    jid = jm.submit(target=lambda j: time.sleep(2), title="t", url="https://x")
    jm.pause(jid)
    # Second call returns True and stays PAUSED, doesn't crash
    assert jm.pause(jid) is True
    assert jm.get(jid).status == JobStatus.PAUSED
    jm.shutdown()


def test_pause_returns_false_for_unknown_id():
    jm = JobManager(max_workers=1, ttl_seconds=60)
    assert jm.pause("nonexistent") is False
    jm.shutdown()


def test_pause_noop_on_terminal_states():
    """Pausing a DONE/ERROR/CANCELLED job is a no-op (returns False)."""
    jm = JobManager(max_workers=1, ttl_seconds=60)
    jid = jm.submit(target=lambda j: None, title="t", url="https://x")
    for _ in range(50):
        if jm.get(jid).status == JobStatus.DONE:
            break
        time.sleep(0.05)
    assert jm.pause(jid) is False
    assert jm.get(jid).status == JobStatus.DONE
    jm.shutdown()
```

- [ ] **Step 5.2: Run tests to verify they fail**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_jobs.py::test_pause_marks_paused_and_kills_process -v`

Expected: FAIL — `'JobManager' object has no attribute 'pause'`.

- [ ] **Step 5.3: Add pause() method to JobManager**

In `jobs.py`, add this method to the `JobManager` class (between `cancel()` and `sweep()`):

```python
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
```

- [ ] **Step 5.4: Run tests to verify they pass**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_jobs.py -v`

Expected: All tests pass.

- [ ] **Step 5.5: Commit**

```bash
git add jobs.py tests/test_jobs.py
git commit -m "$(cat <<'EOF'
feat(jobs): JobManager.pause() — kill process, keep .part files

Sets _was_paused before killing so runner skips _cleanup_glob().
Idempotent on already-paused; no-op on terminal states.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `JobManager.resume()` method

**Files:**
- Modify: `jobs.py` (JobManager class)
- Modify: `tests/test_jobs.py`

- [ ] **Step 6.1: Write the failing tests**

Append to `tests/test_jobs.py`:

```python
def test_resume_re_runs_target_and_clears_paused_flag():
    jm = JobManager(max_workers=1, ttl_seconds=60)
    runs = []

    def work(job: Job):
        runs.append(job.id)

    jid = jm.submit(target=work, title="t", url="https://x")
    # Wait for first run
    for _ in range(50):
        if jm.get(jid).status == JobStatus.DONE:
            break
        time.sleep(0.05)
    # Force into PAUSED for the test
    with jm._lock:
        jm._jobs[jid].status = JobStatus.PAUSED
        jm._jobs[jid]._was_paused = True

    assert jm.resume(jid, target=work) is True
    # Wait for second run
    for _ in range(50):
        if jm.get(jid).status == JobStatus.DONE:
            break
        time.sleep(0.05)
    assert len(runs) == 2
    assert jm.get(jid)._was_paused is False
    jm.shutdown()


def test_resume_returns_false_for_unknown_id():
    jm = JobManager(max_workers=1, ttl_seconds=60)
    assert jm.resume("nope", target=lambda j: None) is False
    jm.shutdown()


def test_resume_no_op_on_already_downloading():
    jm = JobManager(max_workers=1, ttl_seconds=60)
    jid = jm.submit(target=lambda j: time.sleep(0.5), title="t", url="https://x")
    # While DOWNLOADING, resume should return True and not double-submit
    runs = []
    assert jm.resume(jid, target=lambda j: runs.append(1)) is True
    time.sleep(0.6)
    assert len(runs) == 0  # the resume target should not have run
    jm.shutdown()
```

- [ ] **Step 6.2: Run tests to verify they fail**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_jobs.py::test_resume_re_runs_target_and_clears_paused_flag -v`

Expected: FAIL — `'JobManager' object has no attribute 'resume'`.

- [ ] **Step 6.3: Add resume() method**

In `jobs.py`, add this method to `JobManager` after `pause()`:

```python
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
                    if job.status not in {JobStatus.ERROR, JobStatus.CANCELLED, JobStatus.PAUSED}:
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
```

- [ ] **Step 6.4: Run tests to verify they pass**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_jobs.py -v`

Expected: All tests pass.

- [ ] **Step 6.5: Commit**

```bash
git add jobs.py tests/test_jobs.py
git commit -m "$(cat <<'EOF'
feat(jobs): JobManager.resume() — re-submit work to executor

Caller supplies the target thunk (since we can't serialize closures
across restarts). Clears _was_paused, marks DOWNLOADING, persists,
and submits to the executor. Idempotent on already-downloading.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Runner respects `_was_paused` flag

**Files:**
- Modify: `runner.py` (run_download streaming branch)
- Modify: `tests/test_runner.py`

- [ ] **Step 7.1: Write the failing test**

Append to `tests/test_runner.py`:

```python
def test_run_download_skips_cleanup_when_was_paused(monkeypatch, tmp_path):
    """When the caller flags the job as paused, .part files must be preserved."""
    from runner import run_download
    out_template = str(tmp_path / "abc.%(ext)s")
    part_file = tmp_path / "abc.mp4.part"
    part_file.write_bytes(b"partial bytes")
    other_part = tmp_path / "abc.webm"
    other_part.write_bytes(b"x")

    # Build a fake Popen that returns non-zero (as if it was killed)
    class FakeProc:
        returncode = -9
        def __init__(self, *a, **kw):
            self.stdout = iter([])
            self.stderr = iter([])
        def poll(self):
            return -9
        def wait(self, timeout=None):
            return -9
        def kill(self):
            pass

    monkeypatch.setattr("runner.subprocess.Popen", FakeProc)

    # State set by JobManager.pause() before kill
    pause_signal = {"was_paused": True}
    def progress_cb(*args, **kwargs):
        pass
    def register_process(proc):
        pass

    # The streaming path needs to know it was paused. We'll signal via a
    # sentinel kwarg threaded through.
    res = run_download(
        url="https://example.com/v",
        out_template=out_template,
        format_choice="video",
        format_id=None,
        progress_cb=progress_cb,
        register_process=register_process,
        was_paused_check=lambda: pause_signal["was_paused"],
    )
    assert part_file.exists()  # NOT cleaned up
    assert other_part.exists()  # NOT cleaned up


def test_run_download_runs_cleanup_when_not_paused(monkeypatch, tmp_path):
    """When the failure was a real error, cleanup runs as before."""
    from runner import run_download
    out_template = str(tmp_path / "abc.%(ext)s")
    part_file = tmp_path / "abc.mp4.part"
    part_file.write_bytes(b"partial bytes")

    class FakeProc:
        returncode = 1
        def __init__(self, *a, **kw):
            self.stdout = iter([])
            self.stderr = iter(["ERROR: video unavailable\n"])
        def poll(self):
            return 1
        def wait(self, timeout=None):
            return 1
        def kill(self):
            pass

    monkeypatch.setattr("runner.subprocess.Popen", FakeProc)

    res = run_download(
        url="https://example.com/v",
        out_template=out_template,
        format_choice="video",
        format_id=None,
        progress_cb=lambda *a, **k: None,
        register_process=lambda p: None,
        was_paused_check=lambda: False,
    )
    assert not part_file.exists()  # cleaned up
    assert res.error_category is not None
```

- [ ] **Step 7.2: Run tests to verify they fail**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_runner.py::test_run_download_skips_cleanup_when_was_paused -v`

Expected: FAIL — `run_download() got an unexpected keyword argument 'was_paused_check'`.

- [ ] **Step 7.3: Add `was_paused_check` kwarg to run_download**

In `runner.py`, modify the `run_download` signature and the streaming-path cleanup branch.

**Find** the function signature (around line 206):

```python
def run_download(
    *,
    url: str,
    out_template: str,
    format_choice: str,
    format_id: str | None,
    timeout: int = 300,
    progress_cb=None,
    register_process=None,
) -> DownloadResult:
```

**Replace** with:

```python
def run_download(
    *,
    url: str,
    out_template: str,
    format_choice: str,
    format_id: str | None,
    timeout: int = 300,
    progress_cb=None,
    register_process=None,
    was_paused_check: object = None,
) -> DownloadResult:
```

**Then** find the streaming-path failure branch (the block after `proc.wait(timeout=10)` that runs when `proc.returncode != 0`). Replace:

```python
    if proc.returncode != 0:
        _cleanup_glob(out_template)
        stripped = stderr_text.strip()
        return DownloadResult(
            error_category=classify_error(stderr_text),
            error_raw=stripped.splitlines()[-1] if stripped else "",
        )
```

with:

```python
    if proc.returncode != 0:
        # If the JobManager paused this job (vs. a real error), preserve .part
        # files so resume can continue where we left off.
        was_paused = bool(was_paused_check and was_paused_check())
        if not was_paused:
            _cleanup_glob(out_template)
        stripped = stderr_text.strip()
        return DownloadResult(
            error_category="cancelled" if was_paused else classify_error(stderr_text),
            error_raw=stripped.splitlines()[-1] if stripped else "",
        )
```

**Also** find the timeout branch in the streaming path (`if time.monotonic() >= deadline:`) and similarly check `was_paused_check` before cleaning up:

```python
        if time.monotonic() >= deadline:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
            if not (was_paused_check and was_paused_check()):
                _cleanup_glob(out_template)
            return DownloadResult(error_category="timeout", error_raw="download timed out")
```

- [ ] **Step 7.4: Run tests to verify they pass**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_runner.py -v`

Expected: All tests pass.

- [ ] **Step 7.5: Commit**

```bash
git add runner.py tests/test_runner.py
git commit -m "$(cat <<'EOF'
feat(runner): preserve .part files when job was paused

run_download accepts a was_paused_check callable. When the subprocess
exits non-zero AND the job was paused (caller signaled via the
callback), skip _cleanup_glob() so the .part files survive for
resume. Real errors still trigger cleanup as before.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `POST /api/job/<id>/pause` endpoint

**Files:**
- Modify: `app.py:180-195` (after the existing `/cancel` endpoint)
- Modify: `tests/test_endpoints.py`

- [ ] **Step 8.1: Write the failing tests**

Append to `tests/test_endpoints.py`:

```python
def test_pause_endpoint_returns_card_html(client, app):
    jm = app.extensions["trove.jobs"]
    jid = jm.submit(
        target=lambda j: __import__("time").sleep(2),
        title="Test", url="https://example.com/v",
    )
    res = client.post(f"/api/job/{jid}/pause")
    assert res.status_code == 200
    body = res.data.decode()
    assert "is-paused" in body or "paused" in body.lower()


def test_pause_endpoint_404_unknown(client):
    res = client.post("/api/job/unknownid12/pause")
    assert res.status_code == 404
```

- [ ] **Step 8.2: Run tests to verify they fail**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_endpoints.py::test_pause_endpoint_returns_card_html -v`

Expected: FAIL — 404 returned (route doesn't exist).

- [ ] **Step 8.3: Add the endpoint**

In `app.py`, after the existing `api_job_cancel` function (around line 191), add:

```python
    @app.post("/api/job/<job_id>/pause")
    @token_required
    def api_job_pause(job_id):
        ok = job_manager.pause(job_id)
        if not ok:
            return "", 404
        job = job_manager.get(job_id)
        if job is None:
            return "", 404
        return render_template("partials/card.html", card=_card_view(job))
```

- [ ] **Step 8.4: Run tests to verify they pass**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_endpoints.py -v`

Expected: All endpoint tests pass.

- [ ] **Step 8.5: Commit**

```bash
git add app.py tests/test_endpoints.py
git commit -m "$(cat <<'EOF'
feat(api): POST /api/job/<id>/pause

Calls JobManager.pause() and returns the rendered paused card via
the same partials/card.html template the queue uses. Token-protected.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `POST /api/job/<id>/resume` endpoint + `_enqueue_download` resume support

**Files:**
- Modify: `app.py` (`_enqueue_download` to capture resume args; new endpoint)
- Modify: `tests/test_endpoints.py`

- [ ] **Step 9.1: Write the failing tests**

Append to `tests/test_endpoints.py`:

```python
def test_resume_endpoint_returns_card_html(client, app):
    jm = app.extensions["trove.jobs"]
    # Create a paused job with all the resume_args fields populated
    from jobs import Job, JobStatus
    j = Job(
        id="pausedjob1", url="https://example.com/v", title="Test",
        status=JobStatus.PAUSED,
        format_choice="video", format_id=None,
        out_template="/tmp/test.%(ext)s",
    )
    with jm._lock:
        jm._jobs["pausedjob1"] = j
    res = client.post("/api/job/pausedjob1/resume")
    assert res.status_code == 200
    body = res.data.decode()
    assert "downloading" in body.lower() or "is-downloading" in body


def test_resume_endpoint_404_unknown(client):
    res = client.post("/api/job/unknownid12/resume")
    assert res.status_code == 404
```

- [ ] **Step 9.2: Run tests to verify they fail**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_endpoints.py::test_resume_endpoint_returns_card_html -v`

Expected: FAIL — 404 (route missing).

- [ ] **Step 9.3: Update `_enqueue_download` to record resume args, add resume endpoint**

In `app.py`, find `_enqueue_download` (around line 195). Modify it so the Job has `format_choice`, `format_id`, `out_template` populated. Replace the function body with:

```python
    def _enqueue_download(url: str, format_choice: str, format_id, title: str, thumbnail: str = "") -> str:
        def _work(job: Job):
            job.thumbnail = thumbnail
            job.format_choice = format_choice
            job.format_id = format_id
            out_template = str(DOWNLOAD_DIR / f"{job.id}.%(ext)s")
            job.out_template = out_template

            def _on_progress(downloaded, total, speed, eta, frag_idx, frag_count):
                job.downloaded_bytes = downloaded
                job.total_bytes = total
                job.speed = speed
                job.eta = eta
                job.fragment_index = frag_idx
                job.fragment_count = frag_count

            def _register_proc(popen):
                job.process = popen

            result = run_download(
                url=url,
                out_template=out_template,
                format_choice=format_choice,
                format_id=format_id,
                progress_cb=_on_progress,
                register_process=_register_proc,
                was_paused_check=lambda: job._was_paused,
            )
            if result.error_category:
                if not job._was_paused:
                    job.status = JobStatus.ERROR
                    job.error_category = result.error_category
                    job.error_message = result.error_raw
                return
            ext = os.path.splitext(result.file_path)[1] if result.file_path else ""
            job.file_path = result.file_path
            job.filename = sanitize_filename(title, ext)

        return job_manager.submit(target=_work, title=title, url=url)
```

Then add a new endpoint right after `api_job_pause`:

```python
    @app.post("/api/job/<job_id>/resume")
    @token_required
    def api_job_resume(job_id):
        job = job_manager.get(job_id)
        if job is None:
            return "", 404

        # Reconstruct the work thunk from the persisted resume_args.
        url = job.url
        format_choice = job.format_choice
        format_id = job.format_id
        title = job.title
        thumbnail = job.thumbnail
        out_template = job.out_template or str(DOWNLOAD_DIR / f"{job.id}.%(ext)s")

        def _work(j: Job):
            j.thumbnail = thumbnail
            j.format_choice = format_choice
            j.format_id = format_id
            j.out_template = out_template

            def _on_progress(downloaded, total, speed, eta, frag_idx, frag_count):
                j.downloaded_bytes = downloaded
                j.total_bytes = total
                j.speed = speed
                j.eta = eta
                j.fragment_index = frag_idx
                j.fragment_count = frag_count

            def _register_proc(popen):
                j.process = popen

            result = run_download(
                url=url,
                out_template=out_template,
                format_choice=format_choice,
                format_id=format_id,
                progress_cb=_on_progress,
                register_process=_register_proc,
                was_paused_check=lambda: j._was_paused,
            )
            if result.error_category:
                if not j._was_paused:
                    j.status = JobStatus.ERROR
                    j.error_category = result.error_category
                    j.error_message = result.error_raw
                return
            ext = os.path.splitext(result.file_path)[1] if result.file_path else ""
            j.file_path = result.file_path
            j.filename = sanitize_filename(title, ext)

        ok = job_manager.resume(job_id, target=_work)
        if not ok:
            return "", 404
        job = job_manager.get(job_id)
        return render_template("partials/card.html", card=_card_view(job))
```

- [ ] **Step 9.4: Run tests to verify they pass**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/test_endpoints.py -v`

Expected: All endpoint tests pass.

- [ ] **Step 9.5: Run full suite**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/`

Expected: All tests pass.

- [ ] **Step 9.6: Commit**

```bash
git add app.py tests/test_endpoints.py
git commit -m "$(cat <<'EOF'
feat(api): POST /api/job/<id>/resume + capture resume args at submit

_enqueue_download now records format_choice, format_id, and
out_template on the Job at submit time so the resume endpoint can
reconstruct the work thunk from persisted state. Resume endpoint
itself rebuilds the closure from job fields and calls
JobManager.resume().

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Wire JobManager into app with persistence path

**Files:**
- Modify: `app.py` (create_app)

- [ ] **Step 10.1: Update create_app to pass store_path**

In `app.py`, find the `JobManager` instantiation in `create_app` (around line 45):

```python
    job_manager = JobManager(max_workers=MAX_WORKERS, ttl_seconds=JOB_TTL)
```

Replace with:

```python
    job_manager = JobManager(
        max_workers=MAX_WORKERS,
        ttl_seconds=JOB_TTL,
        store_path=DOWNLOAD_DIR / "jobs.json",
    )
```

- [ ] **Step 10.2: Verify Flask still starts**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -c "from app import create_app; create_app()"`

Expected: no exceptions, no output.

- [ ] **Step 10.3: Run full test suite**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/`

Expected: All tests pass.

- [ ] **Step 10.4: Commit**

```bash
git add app.py
git commit -m "$(cat <<'EOF'
feat(app): persist JobManager state to downloads/jobs.json

Wires the production JobManager to the JSON store. On startup the
store loads; DOWNLOADING/QUEUED jobs from the previous session
downgrade to PAUSED so the user can resume them.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Card template — `.is-paused` Jinja branch

**Files:**
- Modify: `templates/partials/card.html`

- [ ] **Step 11.1: Add new Jinja branch for paused state**

In `templates/partials/card.html`, find the `{% elif card.kind == "cancelled" %}` block. Insert a new branch BEFORE it:

```html
{% elif card.kind == "paused" %}
<div
  class="clip is-paused"
  data-job-id="{{ card.id }}"
  data-status="paused"
>
  {{ thumb(card) }}
  <div class="clip-body">
    <p class="clip-title">{{ card.title or "untitled" }}</p>
    <p class="clip-meta">
      {% if card.total_bytes %}
        {{ "%.1f"|format(card.downloaded_bytes / 1048576) }} MB
        <span class="sep">/</span>{{ "%.1f"|format(card.total_bytes / 1048576) }} MB
        <span class="sep">·</span>{{ card.percent }}%
      {% elif card.fragment_count %}
        {{ "%.1f"|format(card.downloaded_bytes / 1048576) }} MB
        <span class="sep">·</span>{{ card.percent }}%
        <span class="sep">·</span>FRAG {{ card.fragment_index }}/{{ card.fragment_count }}
      {% else %}
        PAUSED
      {% endif %}
      {% if card.total_bytes or card.fragment_count %}<span class="sep">·</span>PAUSED{% endif %}
    </p>
  </div>
  <div class="clip-action">
    <button
      type="button"
      class="clip-resume"
      hx-post="/api/job/{{ card.id }}/resume"
      hx-target="closest .clip"
      hx-swap="outerHTML transition:true"
      title="Resume download"
    >▶ resume</button>
    <button
      type="button"
      class="clip-cancel"
      hx-post="/api/job/{{ card.id }}/cancel"
      hx-target="closest .clip"
      hx-swap="outerHTML transition:true"
      title="Cancel download (deletes partial bytes)"
    >✕</button>
  </div>
  <div class="clip-progress">
    <div class="clip-progress-fill" style="width: {{ card.percent or 0 }}%"></div>
  </div>
</div>
```

- [ ] **Step 11.2: Update `_card_view` in app.py to expose `kind == "paused"`**

The existing `_card_view` already maps `job.status.value` → `card.kind`, so `JobStatus.PAUSED` produces `card.kind == "paused"` automatically. No code change needed; just verify by reading `app.py:_card_view` and confirming the chain.

- [ ] **Step 11.3: Smoke test the template render**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python <<'PY'
from app import create_app
from flask import render_template
app = create_app()
with app.test_request_context():
    html = render_template("partials/card.html", card={
        "kind": "paused",
        "id": "abc",
        "title": "test video",
        "thumbnail": "",
        "downloaded_bytes": 1024 * 1024 * 2,
        "total_bytes": 1024 * 1024 * 10,
        "percent": 20,
        "fragment_index": 0,
        "fragment_count": 0,
    })
    assert "is-paused" in html
    assert "▶ resume" in html
    assert "/api/job/abc/resume" in html
    print("OK")
PY
`

Expected: prints `OK`.

- [ ] **Step 11.4: Commit**

```bash
git add templates/partials/card.html
git commit -m "$(cat <<'EOF'
feat(ui): add .clip.is-paused Jinja branch

Renders the paused card state with frozen progress bar at last
percent, MB / MB · NN% · PAUSED meta line, resume + cancel buttons
wired to the new endpoints. data-status="paused" so beforeunload
tracking picks it up.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Card template — pause + cancel buttons on `.is-downloading`

**Files:**
- Modify: `templates/partials/card.html`

- [ ] **Step 12.1: Add buttons inside the downloading-state action column**

Find the `{% elif card.kind in ("queued", "downloading") %}` block. Replace its `<div class="clip-action">` with a richer one that includes pause + cancel:

```html
  <div class="clip-action">
    <span class="clip-saving-stamp">Saving<span class="ellipsis">…</span></span>
    <button
      type="button"
      class="clip-pause"
      hx-post="/api/job/{{ card.id }}/pause"
      hx-target="closest .clip"
      hx-swap="outerHTML transition:true"
      title="Pause download (keeps partial bytes)"
    >⏸ pause</button>
    <button
      type="button"
      class="clip-cancel"
      hx-post="/api/job/{{ card.id }}/cancel"
      hx-target="closest .clip"
      hx-swap="outerHTML transition:true"
      title="Cancel download (deletes partial bytes)"
    >✕</button>
  </div>
```

- [ ] **Step 12.2: Smoke test render**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python <<'PY'
from app import create_app
from flask import render_template
app = create_app()
with app.test_request_context():
    html = render_template("partials/card.html", card={
        "kind": "downloading",
        "id": "abc",
        "title": "test",
        "thumbnail": "",
        "downloaded_bytes": 1024 * 1024,
        "total_bytes": 1024 * 1024 * 5,
        "percent": 20,
        "fragment_index": 0,
        "fragment_count": 0,
    })
    assert "is-downloading" in html
    assert "⏸ pause" in html
    assert "✕" in html
    assert "/api/job/abc/pause" in html
    assert "/api/job/abc/cancel" in html
    print("OK")
PY
`

Expected: prints `OK`.

- [ ] **Step 12.3: Run full test suite**

Run: `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/`

Expected: All tests pass.

- [ ] **Step 12.4: Commit**

```bash
git add templates/partials/card.html
git commit -m "$(cat <<'EOF'
feat(ui): add pause + cancel buttons to downloading card

Both buttons live inside .clip-action alongside the existing
'Saving…' stamp. htmx forms target closest .clip with outerHTML
transition swap so the card flips state in place.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: CSS for paused state + new buttons

**Files:**
- Modify: `styles/input.css`

- [ ] **Step 13.1: Add the paused state + button styles**

In `styles/input.css`, find the `/* CANCELLED */` block (around line 530). Insert the following BEFORE it (so paused, cancelled, error stay in source order matching the design):

```css
  /* PAUSED */
  .clip.is-paused {
    border-color: var(--teal);
    border-style: dashed;
    box-shadow: var(--shadow-stamp);
    filter: saturate(0.6);
  }
  .clip.is-paused .clip-thumb { filter: grayscale(0.3); }
  .clip.is-paused .clip-progress-fill { opacity: 0.6; }
  .clip.is-paused .clip-progress {
    border-top-color: var(--teal);
  }

  .clip-pause, .clip-cancel {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    background: transparent;
    color: var(--teal);
    border: 1.5px solid var(--teal);
    padding: 4px 10px;
    cursor: pointer;
    transition: color 150ms ease-out, border-color 150ms ease-out;
  }
  .clip-pause:hover, .clip-cancel:hover {
    color: var(--orange);
    border-color: var(--orange);
  }
  .clip-pause:focus-visible, .clip-cancel:focus-visible {
    outline: 2px dashed var(--orange);
    outline-offset: 2px;
  }

  .clip-resume {
    font-family: 'Inter', sans-serif;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    background: var(--orange);
    color: var(--light);
    border: 1.5px solid var(--teal);
    padding: 7px 14px;
    box-shadow: var(--shadow-stamp);
    transform: rotate(-1deg);
    cursor: pointer;
    transition: box-shadow 150ms ease-out, transform 80ms ease-out;
  }
  .clip-resume:hover { box-shadow: 3px 3px 0 var(--teal); }
  .clip-resume:active {
    box-shadow: 0 0 0 var(--teal);
    transform: rotate(-1deg) translate(2px, 2px);
  }
  .clip-resume:focus-visible {
    outline: 2px dashed var(--teal);
    outline-offset: 2px;
  }
```

- [ ] **Step 13.2: Rebuild the compiled CSS**

Run from the repo root:

```bash
./tools/tailwindcss -i styles/input.css -o static/app.css --minify
```

Expected: clean compile, no errors.

- [ ] **Step 13.3: Visual smoke test**

Start the dev server: `./trove.sh` (or `/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python app.py`).

Open `http://localhost:8899`, paste a YouTube URL, click Save → Save again on the ready card. Mid-download you should now see two buttons: ⏸ pause and ✕ cancel. Click pause. The card should flip to `.is-paused` (dashed border, slightly desaturated, frozen progress bar) with a `▶ resume` orange-stamp button and a small ✕ cancel.

If pause/resume work end-to-end, this task is done.

- [ ] **Step 13.4: Commit**

```bash
git add styles/input.css static/app.css
git commit -m "$(cat <<'EOF'
feat(ui): CSS for paused state + pause/resume/cancel buttons

.clip.is-paused: dashed teal border, saturate(0.6), frozen progress
bar at 60% opacity. .clip-pause and .clip-cancel: small mono outline
buttons. .clip-resume: orange-stamp matching the hero CTA style with
slight rotation and offset shadow.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Tab-close auto-pause via sendBeacon

**Files:**
- Modify: `templates/base.html`

- [ ] **Step 14.1: Update beforeunload + refreshActiveJobs**

In `templates/base.html`, find the `<script nonce="{{ g.csp_nonce }}">` block. Replace the `beforeunload` listener and `refreshActiveJobs` function:

**Find:**

```js
    window.addEventListener('beforeunload', function () {
      for (var id of window.__troveActiveJobs) {
        try { navigator.sendBeacon('/api/job/' + id + '/cancel'); } catch (_) {}
      }
    });
    function refreshActiveJobs() {
      var active = new Set();
      document.querySelectorAll('[data-job-id][data-status="downloading"]').forEach(function (el) {
        active.add(el.dataset.jobId);
      });
      window.__troveActiveJobs = active;
    }
```

**Replace with:**

```js
    window.addEventListener('beforeunload', function () {
      for (var id of window.__troveActiveJobs) {
        try { navigator.sendBeacon('/api/job/' + id + '/pause'); } catch (_) {}
      }
    });
    function refreshActiveJobs() {
      var active = new Set();
      document
        .querySelectorAll('[data-job-id][data-status="downloading"], [data-job-id][data-status="paused"]')
        .forEach(function (el) {
          active.add(el.dataset.jobId);
        });
      window.__troveActiveJobs = active;
    }
```

- [ ] **Step 14.2: Verify the change took**

Run:

```bash
grep -nE "/api/job.*pause|data-status.*paused" /Users/kaivan108icloud.com/Downloads/trove/templates/base.html
```

Expected output includes both `/api/job/' + id + '/pause` and `data-status="paused"`.

- [ ] **Step 14.3: Smoke test**

With the dev server running, paste a URL → Save → Save the ready card → wait until downloading → close the tab. Reopen `http://localhost:8899`. The card should appear in the queue in `paused` state (loaded from `jobs.json`), with a `▶ resume` button. Click resume — yt-dlp picks up the partial via `--continue` and the bar continues from where it left off.

- [ ] **Step 14.4: Commit**

```bash
git add templates/base.html
git commit -m "$(cat <<'EOF'
feat(ui): tab-close auto-pauses active downloads

beforeunload sendBeacon now hits /api/job/<id>/pause instead of
/cancel — closing the tab preserves work-in-progress, and reopening
the page restores the paused queue from jobs.json.
refreshActiveJobs also tracks data-status="paused" cards so the
beacon fires on second close after F5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Manual QA pass

**Files:** none (verification only)

Run through each scenario. File a follow-up commit if any defect is found.

- [ ] **Step 15.1: Speed flags actually engage**

Paste a YouTube URL with HLS fragments (any non-trivial video). Open the dev tools network tab → confirm yt-dlp is downloading multiple fragments concurrently (check the speed line in the card meta). Approximate baseline: a 4-minute video should now finish in ~25% of the previous time.

- [ ] **Step 15.2: Pause preserves bytes**

Mid-download, click ⏸ pause. The card flips to `.is-paused` with frozen progress bar.
- Check `downloads/` — `.part` files for this job ID still exist.
- Check `downloads/jobs.json` — entry exists with `"status": "paused"` and `downloaded_bytes` matching the last visible value.

- [ ] **Step 15.3: Resume continues from partial**

Click ▶ resume on the paused card. Card flips back to `.is-downloading`. The progress bar starts from approximately where it was — yt-dlp should NOT redownload from 0%. (yt-dlp will print `[download] Resuming from <offset>` to stderr; you can tail `flask` output to confirm.)

- [ ] **Step 15.4: Cancel from paused removes partial**

Pause a download, then click ✕ cancel on the paused card. Card flips to `.is-cancelled`.
- Check `downloads/` — `.part` files for this job ID are gone.
- Check `downloads/jobs.json` — entry is removed (cancel persists).

- [ ] **Step 15.5: Tab close → restart restores paused jobs**

Start a download. Close the browser tab. Confirm the dev server logs `POST /api/job/<id>/pause`. Now stop the dev server (`Ctrl+C`) and restart it. Reopen `http://localhost:8899`. The previously-active card should appear in the queue in paused state, with ▶ resume available.

- [ ] **Step 15.6: DOWNLOADING-at-restart downgrades to PAUSED**

Start a download. While downloading (no manual pause), kill the dev server (`Ctrl+C`) — simulating a crash. Restart. The card should appear in paused state.

- [ ] **Step 15.7: Done jobs survive restart**

Complete a download. Restart the dev server. Reopen the page. The done card should still be visible in the queue.

- [ ] **Step 15.8: Cancelled jobs do NOT persist across restart**

Cancel a job (any state). Restart the dev server. The cancelled card should NOT reappear in the queue.

- [ ] **Step 15.9: Idempotent endpoints**

Use `curl -X POST http://localhost:8899/api/job/<known-id>/pause` twice in a row. Both should return 200 with the paused card HTML. Same for resume on a downloading job — second call returns 200 without error.

- [ ] **Step 15.10: Reduced-motion still works**

In macOS System Settings → Accessibility → Display → "Reduce motion" ON. Pause/resume should still work; the card flip should not animate. Toggle back OFF.

- [ ] **Step 15.11: Final test sweep**

```bash
/Users/kaivan108icloud.com/Downloads/trove/venv/bin/python -m pytest tests/ -v
```

Expected: all tests pass (baseline 63 + ~16 new = ~79 tests passing).

- [ ] **Step 15.12: Optional polish commit**

If you tweaked anything during QA, commit it now:

```bash
git add ...
git commit -m "fix(ui): QA polish from manual pause/resume sweep"
```

---

## Verification matrix

After all tasks complete, the branch produces:

| Surface | Expected |
|---|---|
| `runner.build_download_argv` | argv contains `--concurrent-fragments N` (env-overridable), `--retries 5`, `--fragment-retries 10` |
| `JobStatus` | enum has `PAUSED = "paused"` |
| `Job` dataclass | fields `format_choice`, `format_id`, `out_template`, `_was_paused` populated |
| `jobs_store.py` | atomic JSON read/write; ignores malformed input; version 1 schema |
| `JobManager` | `pause()`, `resume()` methods; `store_path` kwarg; `_persist()` after every state change; `_load_from_store()` downgrades DOWNLOADING/QUEUED→PAUSED, drops CANCELLED |
| `runner.run_download` | accepts `was_paused_check` callable; skips cleanup when true |
| `app.py` | `/api/job/<id>/pause` and `/api/job/<id>/resume` endpoints; resume reconstructs work thunk from persisted args; JobManager wired with `store_path=DOWNLOAD_DIR / "jobs.json"` |
| `templates/partials/card.html` | new `.is-paused` Jinja branch; pause+cancel buttons inside `.is-downloading` |
| `styles/input.css` | `.clip.is-paused`, `.clip-pause`, `.clip-resume`, `.clip-cancel` rules |
| `templates/base.html` | beforeunload sendBeacon → `/pause`; refreshActiveJobs picks up paused cards |
| `pytest tests/` | all tests pass |
| Manual QA §15 | all 11 sub-checks pass |
