"""Prepare local video files for playback in native MP4 players."""
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


class ConversionError(Exception):
    pass


# Only self-contained media containers: an uploaded playlist must never cause
# FFmpeg to open another file or make a network request.
_INPUT = ["-protocol_whitelist", "file", "-format_whitelist",
          "mov,matroska,webm,avi,mpeg,mpegvideo,mpegts,m4v,flv,asf,ogg,h264,hevc,"
          "wav,mp3,aac,flac,aiff,ac3,eac3"]


def convert_mp4(source: Path, output: Path, *, for_download=False, register_process=None) -> Path:
    """Write a new MP4. Download workers may reuse playable MP4s and audio-only inputs."""
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", *_INPUT, "-show_streams", "-show_format",
             "-of", "json", "-i", str(source.resolve())],
            capture_output=True, timeout=60, check=True,
        )
        info = json.loads(probe.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ConversionError("Could not read the media file with ffprobe.") from exc

    streams = info.get("streams", [])
    video = next((s for s in streams if s["codec_type"] == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    audio = [s for s in streams if s["codec_type"] == "audio"]
    if not video:
        if for_download and audio:
            return source
        raise ConversionError("Choose a file with a video track.")

    copy_video = video["codec_name"] == "h264" and video.get("pix_fmt") in ("yuv420p", "yuvj420p")
    copy_audio = [s["codec_name"] == "aac" and s.get("profile") == "LC" for s in audio]
    if (source.suffix.lower() == ".mp4" and "mp4" in info["format"]["format_name"].split(",")
            and copy_video and all(copy_audio)):
        if for_download:
            return source
        shutil.copyfile(source, output)
        return output

    args = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-n", *_INPUT,
            "-i", str(source.resolve()), "-map", f"0:{video['index']}", "-map", "0:a?"]
    if copy_video:
        args += ["-c:v", "copy"]
    else:
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-threads:v", "4",
                 "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-pix_fmt", "yuv420p"]
    for i, compatible in enumerate(copy_audio):
        args += [f"-c:a:{i}", "copy" if compatible else "aac"]
        if not compatible:
            args += [f"-b:a:{i}", "192k"]
    args += ["-tag:v", "avc1", "-movflags", "+faststart", "-f", "mp4", str(output.resolve())]
    try:
        with subprocess.Popen(args, stderr=subprocess.PIPE) as proc:
            if register_process:
                register_process(proc)
            try:
                _, stderr = proc.communicate(timeout=4 * 3600)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                raise ConversionError("MP4 conversion timed out.")
    except OSError as exc:
        raise ConversionError("Could not run FFmpeg.") from exc
    if proc.returncode:
        raise ConversionError(stderr.decode(errors="replace").strip()[-400:] or "MP4 conversion stopped.")
    return output


def prepare_download(source: Path, register_process=None) -> Path:
    """Publish the converted download atomically after FFmpeg has closed the MP4."""
    with TemporaryDirectory(dir=source.parent, prefix=".trove-mp4-") as directory:
        result = convert_mp4(source, Path(directory) / "converted.mp4",
                             for_download=True, register_process=register_process)
        if result == source:
            return source
        destination = source.with_suffix(".mp4")
        result.replace(destination)
        if source != destination:
            source.unlink(missing_ok=True)
        return destination
