"""Manage Trove's whisper.cpp model cache at <repo>/models/.

Files in this dir:
    ggml-<size>.bin                  — the model binary
    ggml-<size>.bin.sha256           — verified hash (one line, hex)
    ACTIVE                           — single-line file: name of active model

The setup wizard owns this dir. The transcriber reads via get_active_path().
"""
from __future__ import annotations
import os
import shutil
import tempfile
from pathlib import Path


# Default location: <repo>/models/. Tests monkeypatch this.
MODELS_DIR: Path = Path(__file__).parent / "models"


# Known whisper.cpp models with HF URLs and verified SHA-256.
# SHA-256 values are from huggingface.co/ggerganov/whisper.cpp; verified
# on first download.
KNOWN_MODELS: dict[str, dict] = {
    "ggml-tiny.bin": {
        "size_bytes": 39_000_000,
        "hf_url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin",
        "sha256": "be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21",
        "label": "tiny",
        "stars": 2,
        "multilingual": True,
    },
    "ggml-base.bin": {
        "size_bytes": 142_000_000,
        "hf_url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin",
        "sha256": "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe",
        "label": "base",
        "stars": 3,
        "multilingual": True,
    },
    "ggml-small.bin": {
        "size_bytes": 466_000_000,
        "hf_url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin",
        "sha256": "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b",
        "label": "small",
        "stars": 4,
        "multilingual": True,
    },
    "ggml-medium.bin": {
        "size_bytes": 1_500_000_000,
        "hf_url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin",
        "sha256": "6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208",
        "label": "medium",
        "stars": 5,
        "multilingual": True,
    },
}


def _ensure_dir() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)


def list_installed() -> list[str]:
    """Return names of installed model .bin files (sorted)."""
    _ensure_dir()
    return sorted(p.name for p in MODELS_DIR.iterdir()
                  if p.suffix == ".bin" and p.name.startswith("ggml-"))


def get_active() -> str | None:
    """Return the name of the active model, or None."""
    _ensure_dir()
    active_file = MODELS_DIR / "ACTIVE"
    if not active_file.exists():
        return None
    name = active_file.read_text().strip()
    if not name or not (MODELS_DIR / name).exists():
        return None
    return name


def get_active_path() -> Path | None:
    """Return the absolute path to the active model, or None."""
    name = get_active()
    if name is None:
        return None
    return MODELS_DIR / name


def set_active(name: str) -> None:
    """Atomically mark `name` as the active model.

    Raises FileNotFoundError if the model isn't installed.
    """
    _ensure_dir()
    if not (MODELS_DIR / name).exists():
        raise FileNotFoundError(f"model not installed: {name}")
    # Atomic write
    fd, tmp_path = tempfile.mkstemp(prefix="ACTIVE.", dir=str(MODELS_DIR))
    try:
        with os.fdopen(fd, "w") as f:
            f.write(name + "\n")
        os.replace(tmp_path, MODELS_DIR / "ACTIVE")
    except Exception:
        try: os.unlink(tmp_path)
        except OSError: pass
        raise


def remove(name: str) -> None:
    """Delete the model file (and its sha256 sidecar). Clears ACTIVE if removing the active one."""
    _ensure_dir()
    bin_path = MODELS_DIR / name
    sha_path = MODELS_DIR / (name + ".sha256")
    active_file = MODELS_DIR / "ACTIVE"
    # Read ACTIVE before removing the binary so the stale-guard doesn't fire.
    was_active = active_file.exists() and active_file.read_text().strip() == name
    if bin_path.exists():
        bin_path.unlink()
    if sha_path.exists():
        sha_path.unlink()
    if was_active:
        try:
            active_file.unlink()
        except OSError:
            pass
