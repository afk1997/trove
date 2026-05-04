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


def test_auto_k_does_not_over_count_for_within_speaker_variation():
    """A single real speaker has natural pitch/volume variation across
    chunks. The encoder produces SLIGHTLY different embeddings per chunk
    even from the same person — auto_k must NOT split that into 3+
    clusters. Real-world over-counting (one ESL clip showed 6 phantom
    speakers for what was clearly 2 speakers) was the trigger for the
    25%-improvement threshold."""
    pytest.importorskip("sklearn")
    import numpy as np
    d = _fresh_diarizer()
    rng = np.random.RandomState(42)
    # 8 embeddings, all 'same speaker' with small per-chunk noise.
    base = np.array([0.5, 0.3, -0.2, 0.1, 0.4, -0.3, 0.2, -0.1])
    embs = np.array([base + rng.normal(0, 0.05, len(base)) for _ in range(8)])
    k = d._auto_k(embs)
    assert k == 1, f"single speaker (within-speaker noise) shouldn't split into k={k}"


def test_auto_k_caps_at_default_max_k():
    """Even with 8 well-separated clusters, default max_k=4 must hold."""
    pytest.importorskip("sklearn")
    import numpy as np
    d = _fresh_diarizer()
    # 8 chunks each anchored to a distinct unit-vector direction
    points = np.eye(8)
    k = d._auto_k(points)
    assert k <= 4, f"default max_k=4 must hold; got k={k}"


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


def test_diarize_merges_consecutive_same_speaker_partials(monkeypatch):
    """v3 pipeline: ``diarize`` collapses runs of same-label partials into
    a single ``SpeakerChunk`` per turn. A 6-partial sequence labelled
    [A,A,A,B,B,B] must come back as exactly two chunks covering each run."""
    monkeypatch.setenv("TROVE_DIARIZATION", "on")
    pytest.importorskip("sklearn")
    import numpy as np
    d = _fresh_diarizer()

    monkeypatch.setattr(d, "_vad_speech_chunks", lambda _p: [{"start": 0.0, "end": 6.0}])

    times = [(float(i), float(i) + 1.0) for i in range(6)]
    embs = np.vstack([
        np.array([[1.0, 0.0]] * 3) + 0.01,
        np.array([[0.0, 1.0]] * 3) + 0.01,
    ])
    monkeypatch.setattr(d, "_continuous_embeddings", lambda _p, _r: (times, embs))
    # Disable smoothing so a clean [0,0,0,1,1,1] survives the median filter
    monkeypatch.setattr(d, "_smooth_labels", lambda labels, window=9: labels)

    out = d.diarize(audio_path="ignored.wav", expected_speakers=2)
    assert len(out) == 2, [(c.start, c.end, c.speaker) for c in out]
    assert out[0].start == 0.0
    assert out[0].end == 3.0
    assert out[1].start == 3.0
    assert out[1].end == 6.0
    assert out[0].speaker != out[1].speaker


def test_diarize_passes_through_explicit_speaker_count(monkeypatch):
    """When expected_speakers is given, _auto_k is bypassed and clamped 1..6."""
    monkeypatch.setenv("TROVE_DIARIZATION", "on")
    pytest.importorskip("sklearn")
    import numpy as np
    d = _fresh_diarizer()

    def fake_vad(_path):
        return [{"start": 0.0, "end": 6.0}]

    def fake_continuous(_p, _r):
        # Six partials, two natural clusters
        times = [(float(i), float(i) + 1.0) for i in range(6)]
        embs = np.vstack([
            np.array([[1.0, 0.0]] * 3) + 0.01,
            np.array([[0.0, 1.0]] * 3) + 0.01,
        ])
        return times, embs

    monkeypatch.setattr(d, "_vad_speech_chunks", fake_vad)
    monkeypatch.setattr(d, "_continuous_embeddings", fake_continuous)
    # Bypass smoothing so 6 deterministic labels survive the median filter
    monkeypatch.setattr(d, "_smooth_labels", lambda labels, window=9: labels)

    out = d.diarize(audio_path="ignored.wav", expected_speakers=2)
    # With 6 partials cleanly split into 3+3 clusters, runs collapse to 2 chunks.
    assert len(out) == 2
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


# ---------------------------------------------------------------------------
# Encoder caching (audit #12): the heavy ``VoiceEncoder`` should be built
# at most once per process — not per diarization job.
# ---------------------------------------------------------------------------

def _install_stub_module(monkeypatch, name: str, **attrs):
    """Install a stub module at ``sys.modules[name]`` for the test.

    If the real module is already imported, monkeypatch.setattr is used
    so mutations to its attributes are auto-reverted (avoiding cross-
    test pollution that breaks the audio-alignment suite).
    """
    if name in sys.modules and sys.modules[name] is not None:
        for k, v in attrs.items():
            monkeypatch.setattr(sys.modules[name], k, v, raising=False)
    else:
        stub = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(stub, k, v)
        monkeypatch.setitem(sys.modules, name, stub)


def test_get_encoder_caches_across_calls(monkeypatch):
    """Two ``_get_encoder()`` calls must return the SAME instance and
    construct ``VoiceEncoder`` exactly once. Per-job instantiation
    (the old behavior) loaded ~50MB of weights every transcribe."""
    d = _fresh_diarizer()
    # Reset any cache prior tests may have populated, AND make sure
    # we don't leak a stub encoder into the real diarizer module that
    # other test files import. monkeypatch reverts both on teardown.
    monkeypatch.setattr(d, "_ENCODER", None, raising=False)
    import diarizer as _real_d  # may be a different module instance
    monkeypatch.setattr(_real_d, "_ENCODER", _real_d._ENCODER, raising=False)

    constructed = []

    class _StubEncoder:
        def __init__(self):
            constructed.append(self)

    _install_stub_module(monkeypatch, "resemblyzer", VoiceEncoder=_StubEncoder)

    e1 = d._get_encoder()
    e2 = d._get_encoder()
    assert e1 is e2, "second call must return the cached encoder"
    assert len(constructed) == 1, \
        f"VoiceEncoder must be constructed once, was {len(constructed)}"


def test_get_encoder_raises_unavailable_when_resemblyzer_missing(monkeypatch):
    d = _fresh_diarizer()
    monkeypatch.setattr(d, "_ENCODER", None, raising=False)

    # Force the lazy import to fail.
    monkeypatch.setitem(sys.modules, "resemblyzer", None)
    with pytest.raises(d.DiarizationUnavailable):
        d._get_encoder()


def test_warm_returns_false_when_flag_off(monkeypatch):
    monkeypatch.setenv("TROVE_DIARIZATION", "off")
    d = _fresh_diarizer()
    assert d.warm() is False


def test_warm_constructs_encoder_when_available(monkeypatch):
    monkeypatch.setenv("TROVE_DIARIZATION", "on")
    d = _fresh_diarizer()
    monkeypatch.setattr(d, "_ENCODER", None, raising=False)
    import diarizer as _real_d
    monkeypatch.setattr(_real_d, "_ENCODER", _real_d._ENCODER, raising=False)

    constructed = []

    class _StubEncoder:
        def __init__(self):
            constructed.append(self)

    # Use _install_stub_module so we don't permanently mutate the real
    # resemblyzer.VoiceEncoder (which would corrupt every later test
    # that calls into the real encoder via _get_encoder).
    _install_stub_module(monkeypatch, "resemblyzer", VoiceEncoder=_StubEncoder)
    _install_stub_module(monkeypatch, "sklearn")
    _install_stub_module(monkeypatch, "torch")

    assert d.warm() is True
    assert len(constructed) == 1
    # Idempotent — second warm() doesn't rebuild.
    assert d.warm() is True
    assert len(constructed) == 1
