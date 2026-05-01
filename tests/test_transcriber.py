import subprocess
import pytest
from pathlib import Path
import transcriber


def test_extract_audio_invokes_ffmpeg(monkeypatch, tmp_path):
    """extract_audio() shells out to ffmpeg with the right args."""
    captured = {}

    def fake_run(argv, **kw):
        captured["argv"] = argv
        # Fake a successful ffmpeg run: create the output file
        Path(argv[-1]).write_bytes(b"WAV-FAKE")
        class _R:
            returncode = 0
            stderr = ""
        return _R()

    monkeypatch.setattr(transcriber.subprocess, "run", fake_run)

    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")
    dst = tmp_path / "out.wav"

    transcriber.extract_audio(str(src), str(dst))

    assert dst.exists()
    argv = captured["argv"]
    assert argv[0] == "ffmpeg"
    assert "-y" in argv
    assert "-ar" in argv and "16000" in argv
    assert "-ac" in argv and "1" in argv
    assert str(src) in argv
    assert str(dst) in argv


def test_extract_audio_raises_on_ffmpeg_failure(monkeypatch, tmp_path):
    def fake_run(argv, **kw):
        class _R:
            returncode = 1
            stderr = "no such file"
        return _R()
    monkeypatch.setattr(transcriber.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="ffmpeg"):
        transcriber.extract_audio(str(tmp_path / "in.mp4"), str(tmp_path / "out.wav"))
