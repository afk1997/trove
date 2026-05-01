"""Manage Trove's whisper.cpp model cache at <repo>/models/.

Files in this dir:
    ggml-<size>.bin                  — the model binary
    ggml-<size>.bin.sha256           — verified hash (one line, hex)
    ACTIVE                           — single-line file: name of active model

The setup wizard owns this dir. The transcriber reads via get_active_path().
"""
from __future__ import annotations
import hashlib
import os
import tempfile
from pathlib import Path
from urllib.request import urlopen as _urlopen

# Re-exported so tests can monkeypatch
urlopen = _urlopen


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


def download(name: str, progress_cb=None, verify: bool = True,
             chunk_size: int = 64 * 1024, timeout: int = 60) -> None:
    """Download a known model from HuggingFace, atomically.

    Writes to <name>.part during transfer; renames to <name> on success.
    Optionally verifies SHA-256 against KNOWN_MODELS metadata.

    Precondition: callers must ensure only one in-flight download per
    model name. The .part file is unguarded; concurrent calls will
    corrupt each other's output. The setup-model endpoint enforces this
    via a single in-process flag (see app.py transcribe_setup_state).

    Raises:
        ValueError: unknown model name, or sha256 mismatch
        OSError: network / disk error (urllib.error.URLError is a
            subclass of OSError on CPython)
    """
    if name not in KNOWN_MODELS:
        raise ValueError(f"unknown model: {name}")
    _ensure_dir()
    meta = KNOWN_MODELS[name]
    final = MODELS_DIR / name
    part = MODELS_DIR / (name + ".part")

    sha = hashlib.sha256()
    received = 0
    total = meta["size_bytes"]

    try:
        with urlopen(meta["hf_url"], timeout=timeout) as resp:
            content_length = resp.headers.get("Content-Length")
            if content_length:
                total = int(content_length)
            with open(part, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    sha.update(chunk)
                    received += len(chunk)
                    if progress_cb:
                        try:
                            progress_cb(received, total)
                        except Exception:
                            pass

        # Verify SHA-256 if requested
        digest = sha.hexdigest()
        if verify and digest != meta["sha256"]:
            part.unlink(missing_ok=True)
            raise ValueError(
                f"sha256 mismatch for {name}: expected {meta['sha256']}, got {digest}"
            )

        # Atomic rename + write sidecar
        os.replace(part, final)
        (MODELS_DIR / (name + ".sha256")).write_text(digest + "\n")
    except Exception:
        # Clean up the .part file on any error
        try: part.unlink(missing_ok=True)
        except OSError: pass
        raise
