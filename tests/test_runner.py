import os
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
