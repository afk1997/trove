"""Machine probe for the transcribe setup wizard.

Pure read-only inspection — values are rendered into the setup UI for
user transparency. Nothing is sent over the wire.
"""
from __future__ import annotations
import os
import platform
import shutil
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None


# Lookup table: realtime factor per (gpu_tier, model_name).
# Public whisper.cpp benchmark approximations. Refined per-machine over
# time once we have actual transcribe runs (deferred per spec §14).
_RTF_TABLE: dict[str, dict[str, float]] = {
    "metal": {
        "ggml-tiny.bin":   10.0,
        "ggml-base.bin":    5.0,
        "ggml-small.bin":   2.0,
        "ggml-medium.bin":  0.8,
    },
    "cuda": {
        "ggml-tiny.bin":   12.0,
        "ggml-base.bin":    6.0,
        "ggml-small.bin":   2.5,
        "ggml-medium.bin":  1.0,
    },
    "cpu": {
        "ggml-tiny.bin":    3.0,
        "ggml-base.bin":    1.5,
        "ggml-small.bin":   0.6,
        "ggml-medium.bin":  0.2,
    },
}


def _detect_gpu() -> str:
    """Return one of: 'metal', 'cuda', 'cpu'."""
    system = platform.system()
    if system == "Darwin" and platform.machine() in ("arm64", "aarch64"):
        return "metal"
    if system == "Linux":
        # Crude check: nvidia-smi available
        if shutil.which("nvidia-smi"):
            return "cuda"
    return "cpu"


def _ram_gb() -> int:
    if psutil is None:
        return 0
    return int(psutil.virtual_memory().total / (1024 ** 3))


def _free_disk_gb(path: str = "/") -> int:
    try:
        st = shutil.disk_usage(path)
        return int(st.free / (1024 ** 3))
    except OSError:
        return 0


def probe() -> dict:
    """Return a dict describing the user's machine. Used by the setup wizard."""
    return {
        "os_name": platform.system(),                # "Darwin" | "Linux" | ...
        "os_version": platform.release(),
        "arch": platform.machine(),                  # "arm64" | "x86_64" | ...
        "cpu_cores": os.cpu_count() or 1,
        "ram_gb": _ram_gb(),
        "free_disk_gb": _free_disk_gb(str(Path(__file__).parent)),
        "gpu": _detect_gpu(),
    }


def speed_estimate(model_name: str) -> float:
    """Realtime factor (×) for the given model on this machine.

    Returns 1.0 if the model name is unknown — caller can render "—".
    """
    gpu = _detect_gpu()
    return _RTF_TABLE.get(gpu, _RTF_TABLE["cpu"]).get(model_name, 1.0)
