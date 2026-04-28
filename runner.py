from __future__ import annotations
import os
import json
import subprocess
import glob
import threading
import time
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


def _resolve_output(out_template: str, format_choice: str) -> DownloadResult:
    """Pick the final output file from the glob (shared by both run paths)."""
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


def _parse_progress_int(s: str) -> int:
    if s in ("NA", "None", ""):
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def _parse_progress_float(s: str) -> float:
    if s in ("NA", "None", ""):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


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
    """Run yt-dlp to download a media file.

    When `progress_cb` and `register_process` are both None, uses a blocking
    subprocess.run() — this is the path the unit tests exercise. When either
    is provided, switches to a streaming Popen() path that emits progress
    events parsed from yt-dlp's --progress-template output.

    progress_cb signature: (downloaded_bytes:int, total_bytes:int, speed:float, eta:int)
    register_process signature: (popen) — called once with the live Popen handle
    so callers can implement cancellation.
    """
    argv = build_download_argv(
        url=url,
        out_template=out_template,
        format_choice=format_choice,
        format_id=format_id,
    )

    # Legacy blocking path: tests monkeypatch subprocess.run, so keep it intact
    # when nothing wants progress streaming.
    if progress_cb is None and register_process is None:
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
        return _resolve_output(out_template, format_choice)

    # Streaming path: Popen + per-line progress parsing.
    progress_argv = [
        "--newline",
        "--progress-template",
        "TROVE_PROG|%(progress.downloaded_bytes)s|%(progress.total_bytes,total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s",
    ]
    streamed_argv = argv[:1] + progress_argv + argv[1:]

    try:
        proc = subprocess.Popen(
            streamed_argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except OSError as e:
        return DownloadResult(error_category="unknown", error_raw=str(e))

    if register_process:
        register_process(proc)

    stderr_buf: list[str] = []

    def _drain_stderr():
        try:
            for line in proc.stderr:
                stderr_buf.append(line)
        except Exception:
            pass

    err_thread = threading.Thread(target=_drain_stderr, daemon=True)
    err_thread.start()

    start = time.monotonic()
    try:
        for line in proc.stdout:
            line = line.rstrip("\r\n")
            if line.startswith("TROVE_PROG|") and progress_cb:
                parts = line.split("|")
                if len(parts) == 5:
                    try:
                        progress_cb(
                            _parse_progress_int(parts[1]),
                            _parse_progress_int(parts[2]),
                            _parse_progress_float(parts[3]),
                            _parse_progress_int(parts[4]),
                        )
                    except Exception:
                        pass
            if time.monotonic() - start > timeout:
                proc.kill()
                _cleanup_glob(out_template)
                return DownloadResult(error_category="timeout", error_raw="download timed out")
    except Exception:
        pass

    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)

    err_thread.join(timeout=2)
    stderr_text = "".join(stderr_buf)

    if proc.returncode != 0:
        _cleanup_glob(out_template)
        stripped = stderr_text.strip()
        return DownloadResult(
            error_category=classify_error(stderr_text),
            error_raw=stripped.splitlines()[-1] if stripped else "",
        )

    return _resolve_output(out_template, format_choice)
