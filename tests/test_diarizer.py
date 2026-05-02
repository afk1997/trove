"""Unit tests for diarizer.py.

These tests deliberately do NOT install the heavy deps (resemblyzer / torch /
silero-vad). They monkey-patch the lazy-import helpers so the clustering
+ auto-K logic can be exercised in isolation.

A real end-to-end smoke test (gated on TROVE_DIARIZATION_E2E=1) is the
right place to verify the pipeline against actual audio; it is not run
in the default suite because it loads ~800MB of models.
"""
from __future__ import annotations

import os
import sys
import types
import importlib

import pytest


# We import the module via a fresh import each test so env-var changes are
# always honored.
def _fresh_diarizer():
    if "diarizer" in sys.modules:
        del sys.modules["diarizer"]
    return importlib.import_module("diarizer")


# ---------------------------------------------------------------------------
# Feature-flag tests
# ---------------------------------------------------------------------------

def test_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("TROVE_DIARIZATION", raising=False)
    d = _fresh_diarizer()
    assert d._flag_enabled() is False
    assert d.available() is False


def test_flag_on_values(monkeypatch):
    d = _fresh_diarizer()
    for v in ("on", "1", "true", "yes", "ON", "True"):
        monkeypatch.setenv("TROVE_DIARIZATION", v)
        assert d._flag_enabled() is True


def test_flag_off_values(monkeypatch):
    d = _fresh_diarizer()
    for v in ("off", "0", "false", "no", "", "  "):
        monkeypatch.setenv("TROVE_DIARIZATION", v)
        assert d._flag_enabled() is False


def test_diarize_raises_when_flag_off(monkeypatch, tmp_path):
    monkeypatch.setenv("TROVE_DIARIZATION", "off")
    d = _fresh_diarizer()
    with pytest.raises(d.DiarizationUnavailable):
        d.diarize(audio_path=str(tmp_path / "missing.wav"))


# ---------------------------------------------------------------------------
# Clustering tests (no heavy deps required if sklearn is available)
# ---------------------------------------------------------------------------

def test_cluster_returns_zero_for_empty():
    pytest.importorskip("sklearn")
    d = _fresh_diarizer()
    assert d._cluster([], 2) == []


def test_cluster_returns_zero_for_single_point():
    pytest.importorskip("sklearn")
    d = _fresh_diarizer()
    import numpy as np
    emb = np.array([[1.0, 0.0, 0.0]])
    assert d._cluster(emb, 2) == [0]


def test_cluster_separates_two_clearly_distinct_speakers():
    pytest.importorskip("sklearn")
    import numpy as np
    d = _fresh_diarizer()
    # Six chunks: three near (1,0,0), three near (0,1,0). Two clusters expected.
    emb = np.array([
        [1.0, 0.05, 0.0],
        [0.95, 0.0, 0.05],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.05],
        [0.05, 0.95, 0.0],
        [0.0, 1.0, 0.0],
    ])
    labels = d._cluster(emb, 2)
    assert len(labels) == 6
    # First three should share a label; last three should share a (different) label
    assert labels[0] == labels[1] == labels[2]
    assert labels[3] == labels[4] == labels[5]
    assert labels[0] != labels[3]


def test_cluster_caps_k_at_n_points():
    pytest.importorskip("sklearn")
    import numpy as np
    d = _fresh_diarizer()
    emb = np.array([[1.0, 0.0], [0.0, 1.0]])
    # Asked for k=5 but only 2 points → should not crash
    labels = d._cluster(emb, 5)
    assert len(labels) == 2


# ---------------------------------------------------------------------------
# Auto-K tests
# ---------------------------------------------------------------------------

def test_auto_k_returns_one_for_few_chunks():
    pytest.importorskip("sklearn")
    import numpy as np
    d = _fresh_diarizer()
    # < 4 chunks → always 1
    assert d._auto_k(np.array([[1.0, 0.0]] * 3)) == 1
    assert d._auto_k(np.array([[1.0, 0.0]] * 1)) == 1


def test_auto_k_detects_two_clusters():
    pytest.importorskip("sklearn")
    import numpy as np
    d = _fresh_diarizer()
    # Eight chunks: four near (1,0), four near (0,1). Should pick k=2.
    emb = np.vstack([
        np.array([[1.0, 0.0]] * 4) + np.random.RandomState(0).normal(0, 0.02, (4, 2)),
        np.array([[0.0, 1.0]] * 4) + np.random.RandomState(1).normal(0, 0.02, (4, 2)),
    ])
    k = d._auto_k(emb)
    assert k == 2


def test_within_cluster_dist_is_zero_for_identical_points():
    pytest.importorskip("sklearn")
    import numpy as np
    d = _fresh_diarizer()
    emb = np.array([[1.0, 0.0]] * 4)
    labels = [0, 0, 0, 0]
    assert d._within_cluster_dist(emb, labels) == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Lazy-import boundary: deps missing should raise DiarizationUnavailable
# ---------------------------------------------------------------------------

def test_vad_raises_unavailable_when_silero_missing(monkeypatch):
    monkeypatch.setenv("TROVE_DIARIZATION", "on")
    d = _fresh_diarizer()
    # Force the import inside _vad_speech_chunks to fail
    monkeypatch.setitem(sys.modules, "silero_vad", None)
    with pytest.raises(d.DiarizationUnavailable):
        d._vad_speech_chunks("anything.wav")


def test_embed_raises_unavailable_when_resemblyzer_missing(monkeypatch):
    monkeypatch.setenv("TROVE_DIARIZATION", "on")
    d = _fresh_diarizer()
    monkeypatch.setitem(sys.modules, "resemblyzer", None)
    with pytest.raises(d.DiarizationUnavailable):
        d._embed_chunks("anything.wav", [{"start": 0, "end": 1}])


def test_diarize_aligns_labels_with_kept_chunks_when_short_chunks_skipped(monkeypatch):
    """Regression: short non-trailing chunks must not misalign speaker labels.

    If _embed_chunks drops a chunk in the middle, _diarize must still pair
    each surviving chunk with the cluster label that actually came from
    embedding *that* chunk (not the chunk at the same positional index in
    the original VAD output).
    """
    monkeypatch.setenv("TROVE_DIARIZATION", "on")
    pytest.importorskip("sklearn")
    import numpy as np
    d = _fresh_diarizer()

    # 5 VAD chunks; the middle one (index 2) is the "short" one that
    # _embed_chunks would normally skip. We simulate that here.
    fake_chunks = [
        {"start": 0.0, "end": 1.0},   # speaker A
        {"start": 1.5, "end": 2.5},   # speaker A
        {"start": 3.0, "end": 3.05},  # SHORT — would be skipped
        {"start": 4.0, "end": 5.0},   # speaker B
        {"start": 5.5, "end": 6.5},   # speaker B
    ]
    monkeypatch.setattr(d, "_vad_speech_chunks", lambda _p: fake_chunks)

    # _embed_chunks returns ONLY the 4 surviving chunks + their embeddings.
    kept = [fake_chunks[0], fake_chunks[1], fake_chunks[3], fake_chunks[4]]
    embs = np.array([
        [1.0, 0.0],
        [1.0, 0.0],
        [0.0, 1.0],
        [0.0, 1.0],
    ])
    monkeypatch.setattr(d, "_embed_chunks", lambda _p, _c: (kept, embs))

    out = d.diarize(audio_path="ignored.wav", expected_speakers=2)

    # The skipped chunk must NOT appear in the output.
    assert len(out) == 4
    assert all(c.start != 3.0 for c in out), "short chunk should be dropped"

    # Crucial: the LAST two surviving chunks (the speaker-B group at
    # 4.0-5.0 and 5.5-6.5) must share a label, distinct from the first
    # two. With the old buggy slicing they would inherit the wrong label.
    by_start = {c.start: c.speaker for c in out}
    assert by_start[0.0] == by_start[1.5]
    assert by_start[4.0] == by_start[5.5]
    assert by_start[0.0] != by_start[4.0]


def test_diarize_passes_through_explicit_speaker_count(monkeypatch):
    """When expected_speakers is given, _auto_k is bypassed and clamped 1..6."""
    monkeypatch.setenv("TROVE_DIARIZATION", "on")
    pytest.importorskip("sklearn")
    import numpy as np
    d = _fresh_diarizer()

    # Stub the heavy steps with deterministic returns
    def fake_vad(_path):
        return [{"start": float(i), "end": float(i) + 0.6} for i in range(6)]

    def fake_embed(_path, _chunks):
        # Six embeddings, two natural clusters
        return np.vstack([
            np.array([[1.0, 0.0]] * 3) + 0.01,
            np.array([[0.0, 1.0]] * 3) + 0.01,
        ])

    monkeypatch.setattr(d, "_vad_speech_chunks", fake_vad)
    monkeypatch.setattr(d, "_embed_chunks", fake_embed)

    out = d.diarize(audio_path="ignored.wav", expected_speakers=2)
    assert len(out) == 6
    assert {c.speaker for c in out} == {"Speaker 1", "Speaker 2"}
    # Clamping
    out_high = d.diarize(audio_path="ignored.wav", expected_speakers=99)
    assert len({c.speaker for c in out_high}) <= 6
    out_low = d.diarize(audio_path="ignored.wav", expected_speakers=0)
    # min clamp to 1 → all same speaker
    assert {c.speaker for c in out_low} == {"Speaker 1"}


def test_diarize_returns_empty_when_no_speech(monkeypatch):
    monkeypatch.setenv("TROVE_DIARIZATION", "on")
    d = _fresh_diarizer()
    monkeypatch.setattr(d, "_vad_speech_chunks", lambda _p: [])
    out = d.diarize(audio_path="ignored.wav")
    assert out == []
