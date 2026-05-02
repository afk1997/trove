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
from dataclasses import dataclass


class DiarizationUnavailable(RuntimeError):
    """Raised when heavy deps aren't installed or the feature flag is off."""


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
    """silero-vad → list of {"start": s, "end": s} dicts."""
    try:
        import torch
        from silero_vad import load_silero_vad, read_audio, get_speech_timestamps
    except Exception as e:
        raise DiarizationUnavailable(f"silero-vad not installed: {e}") from e
    model = load_silero_vad()
    wav = read_audio(audio_path, sampling_rate=16000)
    timestamps = get_speech_timestamps(wav, model, sampling_rate=16000)
    return [{"start": t["start"] / 16000.0, "end": t["end"] / 16000.0}
            for t in timestamps]


def _embed_chunks(audio_path: str, chunks: list[dict]):
    """Resemblyzer voice encoder → (kept_chunks, embeddings).

    Skips chunks shorter than 0.5s (too short for a stable embedding).
    Returns the surviving chunks alongside their embeddings so the
    caller can pair labels with the correct time intervals — a naive
    `chunks[:len(embeddings)]` slice would silently misalign whenever
    a non-trailing short chunk is dropped.
    """
    try:
        from resemblyzer import VoiceEncoder, preprocess_wav
        import numpy as np
    except Exception as e:
        raise DiarizationUnavailable(f"resemblyzer not installed: {e}") from e
    encoder = VoiceEncoder()
    wav = preprocess_wav(audio_path)
    sr = 16000
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


def _auto_k(embeddings, max_k: int = 6) -> int:
    """Choose k between 1 and max_k via a simple silhouette-ish heuristic.

    For < 4 chunks we just return 1 (not enough data to split).
    Otherwise we score each k in 2..max_k by mean cosine distance from
    each point to its assigned centroid; pick the smallest k whose
    additional split doesn't materially shrink the score.
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
    best_k = 1
    best_score = float("inf")
    prev_score = None
    # Absolute floor: once clusters are this tight, splitting further is
    # numerical noise. Without this floor, perfectly-separated test data
    # would walk all the way to max_k because the relative 5%-shrink
    # check below collapses to "0 > 0" → False.
    TIGHT_ENOUGH = 1e-3
    for k in range(2, upper + 1):
        clf = AgglomerativeClustering(
            n_clusters=k, metric="cosine", linkage="average",
        )
        labels = clf.fit_predict(embeddings)
        score = _within_cluster_dist(embeddings, labels)
        if score < best_score:
            best_score = score
            best_k = k
        # Stop if clusters are already essentially perfect, OR if adding
        # another cluster doesn't shrink within-cluster dist by at least 5%.
        if score <= TIGHT_ENOUGH:
            break
        if prev_score is not None and score > prev_score * 0.95:
            break
        prev_score = score
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
