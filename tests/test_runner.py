import os
import subprocess
import pytest
from runner import build_info_argv, build_download_argv


def test_info_argv_dash_dash_separator():
    argv = build_info_argv("https://example.com/video")
    assert argv[-2:] == ["--", "https://example.com/video"]
    assert argv[0] == "yt-dlp"
    assert "--no-playlist" in argv
    assert "-j" in argv


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
