"""Local speaker diarization. No HuggingFace auth, no API keys.

Pipeline: silero-vad → speech chunks → Resemblyzer embeddings →
sklearn AgglomerativeClustering. Realistic accuracy is ~70% on clean
audio (worse than pyannote, but no auth required).

Heavy deps (resemblyzer, silero-vad, scikit-learn, torch) are imported
LAZILY inside the worker functions. The module itself imports cleanly
on a stock Python install, so the rest of the app never blows up just
because diarization isn't available.

Public API
----------
``diarize(audio_path, expected_speakers=None)`` returns a list of
``SpeakerChunk`` objects sorted by start time. Raises ``DiarizationUnavailable``
when the optional dependencies aren't installed.

``available()`` returns True when all heavy deps import successfully.
Use this to short-circuit at the call-site before spending time on a
big audio file.

Feature-flag ``TROVE_DIARIZATION``: when set to "off" / "0" / "false",
``available()`` returns False even if the deps are installed. Default
is "off" because the deps are ~800MB and not bundled with Trove.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass


class DiarizationUnavailable(RuntimeError):
    """Raised when heavy deps aren't installed or the feature flag is off."""


# Process-wide ``VoiceEncoder`` cache. Constructing the encoder loads
# ~50MB of weights and takes a few seconds; per-job instantiation made
# repeated transcribes slow and memory-churny. ``_get_encoder()`` lazily
# builds it once and every later diarize() reuses the same instance.
_ENCODER = None
_ENCODER_LOCK = threading.Lock()


def _get_encoder():
    """Return the cached ``VoiceEncoder``, building it on first use.

    Lazy-imports resemblyzer so the module still loads on a stock
    Python install. Raises ``DiarizationUnavailable`` if the import
    fails.
    """
    global _ENCODER
    with _ENCODER_LOCK:
        if _ENCODER is None:
            try:
                from resemblyzer import VoiceEncoder
            except Exception as e:
                raise DiarizationUnavailable(
                    f"resemblyzer not installed: {e}") from e
            _ENCODER = VoiceEncoder()
        return _ENCODER


def warm() -> bool:
    """Eagerly load the encoder so the first diarize() call is fast.

    Useful for health checks or a "warm models" admin path so users
    aren't surprised by a multi-second pause on their first transcribe.
    Returns True on success, False when diarization isn't available
    (feature flag off or deps missing).
    """
    if not available():
        return False
    try:
        _get_encoder()
        return True
    except DiarizationUnavailable:
        return False


@dataclass
class SpeakerChunk:
    start: float    # seconds
    end: float      # seconds (exclusive)
    speaker: str    # "Speaker 1", "Speaker 2", ...


def _flag_enabled() -> bool:
    """``TROVE_DIARIZATION`` env var. Defaults to off."""
    raw = (os.environ.get("TROVE_DIARIZATION", "off") or "").strip().lower()
    return raw in {"on", "1", "true", "yes"}


def available() -> bool:
    """True iff the feature flag is on AND all heavy deps import OK."""
    if not _flag_enabled():
        return False
    try:
        import resemblyzer  # noqa: F401
        import sklearn  # noqa: F401
        import torch  # noqa: F401
    except Exception:
        return False
    return True


def diarize(*, audio_path: str,
            expected_speakers: int | None = None) -> list[SpeakerChunk]:
    """Run VAD + embedding + clustering on a 16k mono WAV.

    Args:
        audio_path: path to a 16kHz mono WAV (the same one ``transcriber``
            already produces).
        expected_speakers: if set (1..6), force k. Otherwise we auto-detect
            via gap statistic.

    Returns:
        Speaker chunks sorted by start time. Empty list when there's no
        speech detected.

    Raises:
        DiarizationUnavailable: when deps aren't installed or flag is off.
    """
    if not _flag_enabled():
        raise DiarizationUnavailable(
            "TROVE_DIARIZATION is off (set TROVE_DIARIZATION=on to enable)"
        )
    chunks = _vad_speech_chunks(audio_path)
    if not chunks:
        return []
    kept_chunks, embeddings = _embed_chunks(audio_path, chunks)
    if len(embeddings) == 0:
        return []
    if expected_speakers is None:
        n_speakers = _auto_k(embeddings)
    else:
        n_speakers = max(1, min(6, int(expected_speakers)))
    labels = _cluster(embeddings, n_speakers)
    # IMPORTANT: label the chunks that actually got embedded — short chunks
    # were filtered out by _embed_chunks, so a naive `chunks[:len(embeddings)]`
    # would misalign every label after the first skipped chunk.
    out: list[SpeakerChunk] = []
    for c, lbl in zip(kept_chunks, labels):
        out.append(SpeakerChunk(
            start=float(c["start"]),
            end=float(c["end"]),
            speaker=f"Speaker {int(lbl) + 1}",
        ))
    out.sort(key=lambda x: x.start)
    return out


# ----------------------------------------------------------------------
# Internal helpers (each lazy-imports its heavy dep so the module loads
# on a stock Python install).
# ----------------------------------------------------------------------

def _vad_speech_chunks(audio_path: str) -> list[dict]:
    """silero-vad → list of {"start": s, "end": s} dicts.

    silero-vad's bundled ``read_audio`` calls torchaudio for I/O, which on
    torchaudio ≥2.9 requires the optional ``torchcodec`` package and breaks
    with a confusing message when it's missing. We sidestep all of that by
    loading via librosa (already a hard dep through resemblyzer) and feeding
    silero-vad a pre-built tensor.
    """
    try:
        import torch
        from silero_vad import load_silero_vad, get_speech_timestamps
        import librosa
    except Exception as e:
        raise DiarizationUnavailable(f"silero-vad not installed: {e}") from e
    model = load_silero_vad()
    wav, source_sr = librosa.load(audio_path, sr=16000, mono=True)
    wav_tensor = torch.from_numpy(wav)
    timestamps = get_speech_timestamps(wav_tensor, model, sampling_rate=16000)
    return [{"start": t["start"] / 16000.0, "end": t["end"] / 16000.0}
            for t in timestamps]


def _embed_chunks(audio_path: str, chunks: list[dict]):
    """Resemblyzer voice encoder → (kept_chunks, embeddings).

    Skips chunks shorter than 0.5s (too short for a stable embedding).
    Returns the surviving chunks alongside their embeddings so the
    caller can pair labels with the correct time intervals — a naive
    `chunks[:len(embeddings)]` slice would silently misalign whenever
    a non-trailing short chunk is dropped.

    NOTE on audio loading: resemblyzer's stock ``preprocess_wav`` calls
    ``trim_long_silences``, which strips silent regions and shrinks the
    returned array. Chunk timestamps reference the ORIGINAL audio
    timeline, so any later chunk past a silent gap would index past
    the trimmed wav's end and get silently dropped. We instead mirror
    preprocess_wav's load + resample + volume-normalize steps and
    skip the silence trim.
    """
    try:
        from resemblyzer.audio import (
            normalize_volume,
            audio_norm_target_dBFS,
            sampling_rate as _RES_SR,
        )
        import librosa
        import numpy as np
    except Exception as e:
        raise DiarizationUnavailable(f"resemblyzer not installed: {e}") from e
    encoder = _get_encoder()
    wav, source_sr = librosa.load(audio_path, sr=None)
    if source_sr != _RES_SR:
        wav = librosa.resample(wav, orig_sr=source_sr, target_sr=_RES_SR)
    wav = normalize_volume(wav, audio_norm_target_dBFS, increase_only=True)
    sr = _RES_SR
    kept: list[dict] = []
    embeddings = []
    for c in chunks:
        s = int(c["start"] * sr)
        e = int(c["end"] * sr)
        seg = wav[s:e]
        if len(seg) < int(sr * 0.5):
            continue
        embeddings.append(encoder.embed_utterance(seg))
        kept.append(c)
    if not embeddings:
        return kept, np.zeros((0, 256))
    return kept, np.array(embeddings)


def _cluster(embeddings, k: int):
    """Agglomerative cosine clustering. Returns 0..k-1 label per row."""
    try:
        from sklearn.cluster import AgglomerativeClustering
    except Exception as e:
        raise DiarizationUnavailable(f"scikit-learn not installed: {e}") from e
    n = len(embeddings)
    if n == 0:
        return []
    if n == 1 or k <= 1:
        return [0] * n
    k = min(k, n)
    clf = AgglomerativeClustering(
        n_clusters=k,
        metric="cosine",
        linkage="average",
    )
    return list(clf.fit_predict(embeddings))


def _auto_k(embeddings, max_k: int = 4) -> int:
    """Choose k between 1 and max_k by inter-cluster centroid distance.

    Within-speaker cosine distance on Resemblyzer embeddings is typically
    0.05-0.25; between-speaker distance is typically 0.40-0.70. So we can
    discriminate "real different speakers" from "one speaker, varied
    delivery" by requiring every pair of cluster centroids to be at least
    ``MIN_CENTROID_DIST`` apart in cosine distance.

    Walks k upward from 2; stops at the first k whose tightest pair of
    centroids is closer than the threshold (those are the same speaker
    that the clusterer split into two halves). This is much more reliable
    than a within-cluster-distance ratio heuristic, which can't tell a
    real second speaker (~50% drop in within-cluster dist) from a
    well-fitting same-speaker split (~30-50% drop).

    < 4 chunks → k=1 (not enough data).
    """
    try:
        import numpy as np
        from sklearn.cluster import AgglomerativeClustering
    except Exception as e:
        raise DiarizationUnavailable(f"scikit-learn not installed: {e}") from e
    n = len(embeddings)
    if n < 4:
        return 1
    upper = min(max_k, n)

    # Two centroids closer than this in cosine distance are treated as the
    # same speaker. Tuned for Resemblyzer + clean speech; lower threshold
    # (0.20) tolerates more within-speaker variation but lets a borderline
    # second speaker slip through; higher (0.30) is stricter.
    MIN_CENTROID_DIST = 0.25

    best_k = 1
    for k in range(2, upper + 1):
        clf = AgglomerativeClustering(
            n_clusters=k, metric="cosine", linkage="average",
        )
        labels = np.asarray(clf.fit_predict(embeddings))
        centroids = []
        for c in sorted(set(labels.tolist())):
            members = embeddings[labels == c]
            if len(members) == 0:
                continue
            centroids.append(members.mean(axis=0))
        centroids = np.asarray(centroids)
        # Normalize to unit length so dot product = cosine similarity
        norms = np.linalg.norm(centroids, axis=1, keepdims=True)
        normed = centroids / np.maximum(norms, 1e-9)
        cos_sim = normed @ normed.T
        pairwise_dist = 1.0 - cos_sim
        # Ignore self-distances on the diagonal
        np.fill_diagonal(pairwise_dist, np.inf)
        min_inter = float(pairwise_dist.min())
        if min_inter < MIN_CENTROID_DIST:
            # Tightest pair of clusters is too close — they represent the
            # same speaker. The previous k (or k=1) is the answer.
            break
        best_k = k
    return best_k


def _within_cluster_dist(embeddings, labels) -> float:
    """Mean cosine distance from each point to its cluster centroid."""
    import numpy as np
    labels = np.asarray(labels)
    total = 0.0
    n = 0
    for c in set(labels.tolist()):
        members = embeddings[labels == c]
        if len(members) == 0:
            continue
        centroid = members.mean(axis=0)
        cn = np.linalg.norm(centroid) or 1e-9
        for m in members:
            mn = np.linalg.norm(m) or 1e-9
            cos_sim = float((m @ centroid) / (mn * cn))
            total += 1.0 - cos_sim
            n += 1
    return total / n if n else 0.0
