"""Tests for the Job.auto_transcribe field + JobManager.submit kwarg
+ persistence round-trip (Task #5)."""
from jobs import Job, JobManager, JobStatus
from jobs_store import dump_jobs, load_jobs, persist_atomic


def test_job_default_auto_transcribe_is_false():
    j = Job(id="abc", url="https://x", title="t")
    assert j.auto_transcribe is False
    assert j._auto_transcribe_hint is None


def test_submit_sets_auto_transcribe_kwarg():
    jm = JobManager(max_workers=1, ttl_seconds=60)
    jid = jm.submit(target=lambda j: None, title="t", url="https://x",
                    auto_transcribe=True)
    assert jm.get(jid).auto_transcribe is True
    jm.shutdown()


def test_submit_default_auto_transcribe_false():
    jm = JobManager(max_workers=1, ttl_seconds=60)
    jid = jm.submit(target=lambda j: None, title="t", url="https://x")
    assert jm.get(jid).auto_transcribe is False
    jm.shutdown()


def test_persistence_round_trip_preserves_auto_transcribe(tmp_path):
    j = Job(id="abc", url="https://x", title="t",
            status=JobStatus.PAUSED, auto_transcribe=True)
    path = tmp_path / "jobs.json"
    persist_atomic({"abc": j}, path)
    loaded = load_jobs(path)
    assert loaded["abc"].auto_transcribe is True
