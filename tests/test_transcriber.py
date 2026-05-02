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


def test_run_transcribe_returns_structured_result(monkeypatch, tmp_path):
    """run_transcribe wraps pywhispercpp Model and returns a TranscriptResult.

    pywhispercpp emits one Segment per word when configured with
    token_timestamps=True + max_len=1 + split_on_word=True. Each Segment has
    integer t0/t1 in centiseconds (1/100 sec).
    """
    fake_segments = [
        type("S", (), {"text": "hello", "t0": 0,  "t1": 50})(),
        type("S", (), {"text": "world", "t0": 50, "t1": 100})(),
    ]

    class FakeModel:
        def __init__(self, model_path, **kw):
            pass
        def transcribe(self, audio, **kw):
            return fake_segments
        def detected_language(self):
            return "en"

    monkeypatch.setattr(transcriber, "_load_pywhispercpp_model", lambda path: FakeModel(path))

    audio = tmp_path / "x.wav"
    audio.write_bytes(b"WAV")

    progress_events = []
    res = transcriber.run_transcribe(
        audio_path=str(audio),
        model_path=str(tmp_path / "ggml-base.bin"),
        progress_cb=lambda pct: progress_events.append(pct),
        cancel_check=lambda: False,
    )

    assert isinstance(res, transcriber.TranscriptResult)
    assert res.language == "en"
    assert res.error is None
    assert len(res.words) == 2
    assert res.words[0]["w"] == "hello"
    assert res.words[0]["start"] == 0.0
    assert res.words[0]["end"] == 0.5
    assert res.words[1]["w"] == "world"
    # Words within the gap threshold group into one paragraph
    assert len(res.segments) == 1
    assert res.segments[0]["text"] == "hello world"
    assert any(p == 100 for p in progress_events)


def test_run_transcribe_groups_words_into_paragraphs(monkeypatch, tmp_path):
    """Words separated by a >1s gap form separate paragraphs."""
    fake_segments = [
        type("S", (), {"text": "first",  "t0": 0,    "t1": 50})(),
        type("S", (), {"text": "para",   "t0": 50,   "t1": 100})(),
        # 2-second gap (200 centiseconds)
        type("S", (), {"text": "second", "t0": 300,  "t1": 400})(),
        type("S", (), {"text": "para",   "t0": 400,  "t1": 500})(),
    ]

    class FakeModel:
        def __init__(self, *a, **kw): pass
        def transcribe(self, *a, **kw): return fake_segments
        def detected_language(self): return ""

    monkeypatch.setattr(transcriber, "_load_pywhispercpp_model", lambda p: FakeModel())

    audio = tmp_path / "x.wav"
    audio.write_bytes(b"WAV")
    res = transcriber.run_transcribe(
        audio_path=str(audio),
        model_path=str(tmp_path / "m.bin"),
    )
    assert res.error is None
    assert len(res.segments) == 2
    assert res.segments[0]["text"] == "first para"
    assert res.segments[1]["text"] == "second para"


def test_run_transcribe_cancellable(monkeypatch, tmp_path):
    """If cancel_check returns True before transcription, run_transcribe returns
    a TranscriptResult with error='cancelled' and no segments.
    """
    class FakeModel:
        def __init__(self, *a, **kw): pass
        def transcribe(self, *a, **kw): return []
        def detected_language(self): return ""

    monkeypatch.setattr(transcriber, "_load_pywhispercpp_model", lambda path: FakeModel())

    audio = tmp_path / "x.wav"
    audio.write_bytes(b"WAV")

    res = transcriber.run_transcribe(
        audio_path=str(audio),
        model_path=str(tmp_path / "m.bin"),
        progress_cb=lambda pct: None,
        cancel_check=lambda: True,  # cancel before run
    )
    assert res.error == "cancelled"


def test_write_artifacts_produces_all_four_files(tmp_path):
    res = transcriber.TranscriptResult(
        language="en",
        duration=2.0,
        segments=[
            {"start": 0.0, "end": 1.0, "text": "hello world",
             "words": [{"w": "hello", "start": 0.0, "end": 0.5},
                       {"w": "world", "start": 0.5, "end": 1.0}]},
            {"start": 1.0, "end": 2.0, "text": "second segment",
             "words": [{"w": "second", "start": 1.0, "end": 1.5},
                       {"w": "segment", "start": 1.5, "end": 2.0}]},
        ],
        words=[
            {"w": "hello", "start": 0.0, "end": 0.5},
            {"w": "world", "start": 0.5, "end": 1.0},
            {"w": "second", "start": 1.0, "end": 1.5},
            {"w": "segment", "start": 1.5, "end": 2.0},
        ],
        error=None,
    )
    transcriber.write_artifacts(res, str(tmp_path / "abc"))

    for ext in (".txt", ".srt", ".vtt", ".words.json"):
        assert (tmp_path / f"abc{ext}").exists()

    txt = (tmp_path / "abc.txt").read_text()
    assert "hello world" in txt
    assert "second segment" in txt

    srt = (tmp_path / "abc.srt").read_text()
    assert "1\n00:00:00,000 --> 00:00:01,000" in srt
    assert "2\n00:00:01,000 --> 00:00:02,000" in srt

    vtt = (tmp_path / "abc.vtt").read_text()
    assert vtt.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:01.000" in vtt
