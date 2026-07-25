import os
import subprocess
import sys
from pathlib import Path

import pytest
import runner
from runner import build_info_argv, build_download_argv


def test_info_argv_dash_dash_separator():
    argv = build_info_argv("https://example.com/video")
    assert argv[-2:] == ["--", "https://example.com/video"]
    # _ytdlp_bin() resolves to an absolute path when a venv-local yt-dlp
    # exists, so assert on the program name rather than the whole string.
    assert os.path.basename(argv[0]) == "yt-dlp"
    assert "--no-playlist" in argv
    assert "-j" in argv


def test_ytdlp_bin_prefers_venv_local_binary(tmp_path, monkeypatch):
    """A yt-dlp sitting next to the interpreter wins over PATH."""
    fake_bin = tmp_path / "yt-dlp"
    fake_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
    assert runner._ytdlp_bin() == str(fake_bin)


def test_ytdlp_bin_falls_back_to_path(tmp_path, monkeypatch):
    """With no venv-local copy, fall back to whatever PATH resolves."""
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
    assert runner._ytdlp_bin() == "yt-dlp"


def test_impersonate_absent_by_default(monkeypatch):
    monkeypatch.delenv("TROVE_IMPERSONATE", raising=False)
    assert "--impersonate" not in build_info_argv("https://example.com/v")


def test_impersonate_injected_when_env_set(monkeypatch):
    monkeypatch.setenv("TROVE_IMPERSONATE", "chrome")
    argv = build_info_argv("https://example.com/v")
    assert argv[argv.index("--impersonate") + 1] == "chrome"
    # Must stay in front of the `--` separator, or yt-dlp reads it as a URL.
    assert argv.index("--impersonate") < argv.index("--")


def test_impersonate_ignores_blank_env(monkeypatch):
    monkeypatch.setenv("TROVE_IMPERSONATE", "   ")
    assert "--impersonate" not in build_download_argv(
        url="https://example.com/v",
        out_template="/tmp/out.%(ext)s",
        format_choice="video",
        format_id=None,
    )


def test_info_argv_injects_cookies_when_env_set(monkeypatch):
    monkeypatch.setenv("TROVE_COOKIES_FROM_BROWSER", "safari")
    argv = build_info_argv("https://example.com/video")
    assert "--cookies-from-browser" in argv
    assert argv[argv.index("--cookies-from-browser") + 1] == "safari"


def test_info_argv_ignores_blank_cookie_env(monkeypatch):
    monkeypatch.setenv("TROVE_COOKIES_FROM_BROWSER", "")
    argv = build_info_argv("https://example.com/video")
    assert "--cookies-from-browser" not in argv


def test_download_argv_audio_mode(tmp_path):
    argv = build_download_argv(
        url="https://example.com/v",
        out_template=str(tmp_path / "out.%(ext)s"),
        format_choice="audio",
        format_id=None,
    )
    assert "-x" in argv
    assert "--audio-format" in argv
    assert argv[argv.index("--audio-format") + 1] == "mp3"
    assert argv[-2:] == ["--", "https://example.com/v"]


def test_download_argv_video_with_format_id(tmp_path):
    argv = build_download_argv(
        url="https://example.com/v",
        out_template=str(tmp_path / "out.%(ext)s"),
        format_choice="video",
        format_id="137",
    )
    assert "-f" in argv
    assert argv[argv.index("-f") + 1] == "137+bestaudio/best"
    assert "--merge-output-format" in argv
    assert argv[argv.index("--merge-output-format") + 1] == "mp4"
    assert argv[-2:] == ["--", "https://example.com/v"]


def test_download_argv_video_default_format(tmp_path):
    argv = build_download_argv(
        url="https://example.com/v",
        out_template=str(tmp_path / "out.%(ext)s"),
        format_choice="video",
        format_id=None,
    )
    assert argv[argv.index("-f") + 1] == "bestvideo+bestaudio/best"


def test_download_argv_rejects_argv_lookalike_url():
    with pytest.raises(ValueError):
        build_download_argv(
            url="--exec=touch /tmp/pwned",
            out_template="x",
            format_choice="video",
            format_id=None,
        )


from runner import classify_error


@pytest.mark.parametrize("stderr,expected", [
    ("ERROR: Unsupported URL: foo", "unsupported_url"),
    ("ERROR: [youtube] Video unavailable", "private_or_unavailable"),
    ("ERROR: Private video. Sign in if you've been granted access", "private_or_unavailable"),
    ("ERROR: Sign in to confirm your age", "auth_required"),
    ("ERROR: This video is not available in your country", "geo_restricted"),
    ("ERROR: HTTP Error 403: Forbidden", "auth_required"),
    ("ERROR: HTTP Error 429: Too Many Requests", "rate_limited"),
    ("ERROR: HTTP Error 404: Not Found", "private_or_unavailable"),
    ("ERROR: unable to download video data: HTTP Error 403: Forbidden", "auth_required"),
    ("ERROR: [generic] some weird thing", "unknown"),
    ("ERROR: Unable to connect to proxy", "network"),
    ("ERROR: Read timed out.", "timeout"),
    ("", "unknown"),
])
def test_classify_error(stderr, expected):
    assert classify_error(stderr) == expected


import json
from unittest.mock import patch
from runner import run_info, InfoResult


def test_run_info_success(monkeypatch):
    fake_stdout = json.dumps({
        "title": "T",
        "thumbnail": "https://x/y.jpg",
        "duration": 30,
        "uploader": "U",
        "formats": [
            {"format_id": "137", "height": 1080, "vcodec": "avc1", "tbr": 5000},
            {"format_id": "136", "height": 720, "vcodec": "avc1", "tbr": 2500},
        ],
    })

    class FakeCompleted:
        returncode = 0
        stdout = fake_stdout
        stderr = ""

    monkeypatch.setattr("runner.subprocess.run", lambda *a, **kw: FakeCompleted())

    res = run_info("https://example.com/v")
    assert isinstance(res, InfoResult)
    assert res.title == "T"
    assert res.uploader == "U"
    assert res.duration == 30
    assert len(res.formats) == 2
    assert res.formats[0]["height"] == 1080
    assert res.formats[0]["label"] == "1080p"


def test_run_info_handles_multiline_stdout(monkeypatch):
    obj = {"title": "first", "thumbnail": "", "duration": 0, "uploader": "", "formats": []}
    fake = json.dumps(obj) + "\n" + json.dumps({"title": "second"})

    class FakeCompleted:
        returncode = 0
        stdout = fake
        stderr = ""

    monkeypatch.setattr("runner.subprocess.run", lambda *a, **kw: FakeCompleted())

    res = run_info("https://example.com/v")
    assert res.title == "first"


def test_run_info_returns_error_on_nonzero(monkeypatch):
    class FakeCompleted:
        returncode = 1
        stdout = ""
        stderr = "ERROR: HTTP Error 403: Forbidden"

    monkeypatch.setattr("runner.subprocess.run", lambda *a, **kw: FakeCompleted())

    res = run_info("https://example.com/v")
    assert res.error_category == "auth_required"
    assert res.title is None


from runner import run_download, DownloadResult


def test_run_download_success(monkeypatch, tmp_path):
    out_template = str(tmp_path / "abc.%(ext)s")
    target = tmp_path / "abc.mp4"
    target.write_bytes(b"fakempegdata")

    class FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr("runner.subprocess.run", lambda *a, **kw: FakeCompleted())

    res = run_download(
        url="https://example.com/v",
        out_template=out_template,
        format_choice="video",
        format_id=None,
    )
    assert isinstance(res, DownloadResult)
    assert res.error_category is None
    assert res.file_path == str(target)


def test_run_download_audio_must_be_mp3(monkeypatch, tmp_path):
    out_template = str(tmp_path / "abc.%(ext)s")
    leftover = tmp_path / "abc.webm"
    leftover.write_bytes(b"x")

    class FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr("runner.subprocess.run", lambda *a, **kw: FakeCompleted())

    res = run_download(
        url="https://example.com/v",
        out_template=out_template,
        format_choice="audio",
        format_id=None,
    )
    assert res.error_category == "unknown"
    assert "mp3" in (res.error_raw or "").lower()


def test_run_download_cleans_orphans_on_timeout(monkeypatch, tmp_path):
    out_template = str(tmp_path / "abc.%(ext)s")
    (tmp_path / "abc.part").write_bytes(b"x")
    (tmp_path / "abc.webm").write_bytes(b"x")

    def _raise(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="yt-dlp", timeout=1)

    monkeypatch.setattr("runner.subprocess.run", _raise)

    res = run_download(
        url="https://example.com/v",
        out_template=out_template,
        format_choice="video",
        format_id=None,
    )
    assert res.error_category == "timeout"
    assert not (tmp_path / "abc.part").exists()
    assert not (tmp_path / "abc.webm").exists()


def test_download_argv_includes_concurrent_fragments():
    argv = build_download_argv(
        url="https://example.com/v",
        out_template="/tmp/x.%(ext)s",
        format_choice="video",
        format_id=None,
    )
    idx = argv.index("--concurrent-fragments")
    assert argv[idx + 1] == "4"  # default


def test_download_argv_concurrent_fragments_env_clamps_high(monkeypatch):
    monkeypatch.setenv("TROVE_CONCURRENT_FRAGMENTS", "100")
    argv = build_download_argv(
        url="https://example.com/v", out_template="/tmp/x.%(ext)s",
        format_choice="video", format_id=None,
    )
    idx = argv.index("--concurrent-fragments")
    assert argv[idx + 1] == "32"  # clamped to max


def test_download_argv_concurrent_fragments_env_clamps_low(monkeypatch):
    monkeypatch.setenv("TROVE_CONCURRENT_FRAGMENTS", "0")
    argv = build_download_argv(
        url="https://example.com/v", out_template="/tmp/x.%(ext)s",
        format_choice="video", format_id=None,
    )
    idx = argv.index("--concurrent-fragments")
    assert argv[idx + 1] == "1"  # clamped to min


def test_download_argv_concurrent_fragments_env_handles_garbage(monkeypatch):
    """Non-int env var should fall back to default 4, not crash."""
    monkeypatch.setenv("TROVE_CONCURRENT_FRAGMENTS", "not-a-number")
    argv = build_download_argv(
        url="https://example.com/v", out_template="/tmp/x.%(ext)s",
        format_choice="video", format_id=None,
    )
    idx = argv.index("--concurrent-fragments")
    assert argv[idx + 1] == "4"  # fallback to default


def test_download_argv_includes_retry_flags():
    argv = build_download_argv(
        url="https://example.com/v",
        out_template="/tmp/x.%(ext)s",
        format_choice="video",
        format_id=None,
    )
    r_idx = argv.index("--retries")
    fr_idx = argv.index("--fragment-retries")
    assert argv[r_idx + 1] == "5"
    assert argv[fr_idx + 1] == "10"


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
