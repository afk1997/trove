from __future__ import annotations
import os


def _cookie_args() -> list[str]:
    browser = os.environ.get("TROVE_COOKIES_FROM_BROWSER", "").strip()
    if not browser:
        return []
    return ["--cookies-from-browser", browser]


def _check_url_shape(url: str) -> None:
    if not url or url.startswith("-"):
        raise ValueError("URL has CLI-option shape; rejected")


def build_info_argv(url: str) -> list[str]:
    """Build argv for `yt-dlp -j` (info dump). Always uses `--` separator."""
    _check_url_shape(url)
    return [
        "yt-dlp",
        "--no-playlist",
        "-j",
        *_cookie_args(),
        "--",
        url,
    ]


def build_download_argv(
    *,
    url: str,
    out_template: str,
    format_choice: str,
    format_id: str | None,
) -> list[str]:
    """Build argv for the actual download. Always uses `--` separator."""
    _check_url_shape(url)
    argv: list[str] = [
        "yt-dlp",
        "--no-playlist",
        "-o", out_template,
        *_cookie_args(),
    ]
    if format_choice == "audio":
        argv += ["-x", "--audio-format", "mp3"]
    elif format_id:
        argv += ["-f", f"{format_id}+bestaudio/best", "--merge-output-format", "mp4"]
    else:
        argv += ["-f", "bestvideo+bestaudio/best", "--merge-output-format", "mp4"]
    argv += ["--", url]
    return argv
