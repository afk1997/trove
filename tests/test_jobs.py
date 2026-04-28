import os
import time
import pytest
from jobs import JobManager, Job, JobStatus


def test_submit_returns_job_id_and_marks_queued():
    jm = JobManager(max_workers=1, ttl_seconds=60)
    jid = jm.submit(target=lambda j: None, title="hi", url="https://x")
    assert isinstance(jid, str) and len(jid) == 10
    j = jm.get(jid)
    assert j.title == "hi"
    assert j.status in {JobStatus.QUEUED, JobStatus.DOWNLOADING}
    jm.shutdown()


def test_submit_runs_target_and_marks_done(tmp_path):
    jm = JobManager(max_workers=1, ttl_seconds=60)
    flag = tmp_path / "done.txt"

    def work(job: Job):
        flag.write_text("ok")

    jid = jm.submit(target=work, title="t", url="https://x")
    for _ in range(50):
        if jm.get(jid).status == JobStatus.DONE:
            break
        time.sleep(0.05)
    assert flag.read_text() == "ok"
    assert jm.get(jid).status == JobStatus.DONE
    jm.shutdown()


def test_submit_marks_error_when_target_raises():
    jm = JobManager(max_workers=1, ttl_seconds=60)

    def boom(job: Job):
        raise RuntimeError("nope")

    jid = jm.submit(target=boom, title="t", url="https://x")
    for _ in range(50):
        if jm.get(jid).status == JobStatus.ERROR:
            break
        time.sleep(0.05)
    assert jm.get(jid).status == JobStatus.ERROR
    jm.shutdown()


def test_cancel_marks_cancelled_for_done_job():
    jm = JobManager(max_workers=1, ttl_seconds=60)

    def work(job: Job):
        pass

    jid = jm.submit(target=work, title="t", url="https://x")
    for _ in range(50):
        if jm.get(jid).status == JobStatus.DONE:
            break
        time.sleep(0.05)
    cancelled = jm.cancel(jid)
    assert cancelled is True
    assert jm.get(jid).status == JobStatus.CANCELLED
    jm.shutdown()


def test_pool_full_returns_overflow():
    jm = JobManager(max_workers=1, ttl_seconds=60, queue_size=0)
    started = []

    def slow(job: Job):
        started.append(job.id)
        time.sleep(0.5)

    j1 = jm.submit(target=slow, title="a", url="https://x")
    with pytest.raises(RuntimeError):
        jm.submit(target=slow, title="b", url="https://y")
    jm.shutdown(wait=True)


def test_ttl_sweep_removes_old_done_jobs(tmp_path):
    jm = JobManager(max_workers=1, ttl_seconds=0)  # zero = sweep immediately

    def work(job: Job):
        f = tmp_path / "out.bin"
        f.write_bytes(b"x")
        job.file_path = str(f)

    jid = jm.submit(target=work, title="t", url="https://x")
    for _ in range(50):
        if jm.get(jid).status == JobStatus.DONE:
            break
        time.sleep(0.05)
    jm.sweep()
    assert jm.get(jid) is None
    assert not (tmp_path / "out.bin").exists()
    jm.shutdown()
