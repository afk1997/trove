from __future__ import annotations
import os
import json
import subprocess
import glob
from dataclasses import dataclass, field


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


def classify_error(stderr: str) -> str:
    """Map yt-dlp stderr to a stable category enum string."""
    s = (stderr or "").lower()
    if not s:
        return "unknown"
    if "unsupported url" in s:
        return "unsupported_url"
    if "video unavailable" in s or "private video" in s or "http error 404" in s:
        return "private_or_unavailable"
    if "sign in" in s or "http error 401" in s or "http error 403" in s:
        return "auth_required"
    if "http error 429" in s or "too many requests" in s or "rate limit" in s:
        return "rate_limited"
    if "not available in your country" in s or "geo" in s and "restrict" in s:
        return "geo_restricted"
    if "timed out" in s or "timeout" in s:
        return "timeout"
    if "unable to connect" in s or "network" in s or "name or service not known" in s:
        return "network"
    return "unknown"


@dataclass
class InfoResult:
    title: str | None = None
    thumbnail: str = ""
    duration: int | None = None
    uploader: str = ""
    formats: list[dict] = field(default_factory=list)
    error_category: str | None = None
    error_raw: str = ""


def _build_quality_options(raw_formats: list[dict]) -> list[dict]:
    """Pick the best (highest tbr) format per resolution, sorted desc by height."""
    best_by_height: dict[int, dict] = {}
    for f in raw_formats:
        h = f.get("height")
        if not h or f.get("vcodec", "none") == "none":
            continue
        tbr = f.get("tbr") or 0
        if h not in best_by_height or tbr > (best_by_height[h].get("tbr") or 0):
            best_by_height[h] = f
    out = [
        {"id": f["format_id"], "label": f"{h}p", "height": h}
        for h, f in best_by_height.items()
    ]
    out.sort(key=lambda x: x["height"], reverse=True)
    return out


def run_info(url: str, *, timeout: int = 60) -> InfoResult:
    argv = build_info_argv(url)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return InfoResult(error_category="timeout", error_raw="info fetch timed out")
    if proc.returncode != 0:
        return InfoResult(
            error_category=classify_error(proc.stderr),
            error_raw=proc.stderr.strip(),
        )
    line = (proc.stdout or "").splitlines()[0] if proc.stdout else ""
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return InfoResult(error_category="unknown", error_raw="invalid JSON from yt-dlp")
    return InfoResult(
        title=data.get("title", ""),
        thumbnail=data.get("thumbnail", "") or "",
        duration=data.get("duration"),
        uploader=data.get("uploader", "") or "",
        formats=_build_quality_options(data.get("formats", [])),
    )


@dataclass
class DownloadResult:
    file_path: str | None = None
    error_category: str | None = None
    error_raw: str = ""


def _cleanup_glob(out_template: str) -> None:
    base = out_template.replace("%(ext)s", "*")
    for f in glob.glob(base):
        try:
            os.remove(f)
        except OSError:
            pass


def run_download(
    *,
    url: str,
    out_template: str,
    format_choice: str,
    format_id: str | None,
    timeout: int = 300,
) -> DownloadResult:
    argv = build_download_argv(
        url=url,
        out_template=out_template,
        format_choice=format_choice,
        format_id=format_id,
    )
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        _cleanup_glob(out_template)
        return DownloadResult(error_category="timeout", error_raw="download timed out")
    if proc.returncode != 0:
        _cleanup_glob(out_template)
        stripped = (proc.stderr or "").strip()
        return DownloadResult(
            error_category=classify_error(proc.stderr),
            error_raw=stripped.splitlines()[-1] if stripped else "",
        )

    base_glob = out_template.replace("%(ext)s", "*")
    files = sorted(glob.glob(base_glob))
    if not files:
        return DownloadResult(error_category="unknown", error_raw="no output file found")

    if format_choice == "audio":
        mp3s = [f for f in files if f.endswith(".mp3")]
        if not mp3s:
            for f in files:
                try:
                    os.remove(f)
                except OSError:
                    pass
            return DownloadResult(
                error_category="unknown",
                error_raw="audio conversion did not produce mp3",
            )
        chosen = mp3s[0]
        leftovers = [f for f in files if f != chosen]
    else:
        mp4s = [f for f in files if f.endswith(".mp4")]
        chosen = mp4s[0] if mp4s else files[0]
        leftovers = [f for f in files if f != chosen]

    for f in leftovers:
        try:
            os.remove(f)
        except OSError:
            pass

    return DownloadResult(file_path=chosen)
