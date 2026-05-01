import os
import pytest
from pathlib import Path
import models_store


@pytest.fixture()
def tmp_models_dir(tmp_path, monkeypatch):
    """Re-point models_store at an empty temp dir for each test."""
    monkeypatch.setattr(models_store, "MODELS_DIR", tmp_path)
    return tmp_path


def test_list_installed_empty(tmp_models_dir):
    assert models_store.list_installed() == []


def test_list_installed_returns_only_ggml_bins(tmp_models_dir):
    (tmp_models_dir / "ggml-tiny.bin").write_bytes(b"x")
    (tmp_models_dir / "ggml-base.bin").write_bytes(b"x")
    (tmp_models_dir / "junk.txt").write_bytes(b"x")
    assert sorted(models_store.list_installed()) == ["ggml-base.bin", "ggml-tiny.bin"]


def test_get_active_returns_none_when_no_active_file(tmp_models_dir):
    assert models_store.get_active() is None


def test_set_and_get_active(tmp_models_dir):
    (tmp_models_dir / "ggml-base.bin").write_bytes(b"x")
    models_store.set_active("ggml-base.bin")
    assert models_store.get_active() == "ggml-base.bin"
    assert (tmp_models_dir / "ACTIVE").read_text().strip() == "ggml-base.bin"


def test_set_active_refuses_uninstalled_model(tmp_models_dir):
    with pytest.raises(FileNotFoundError):
        models_store.set_active("ggml-medium.bin")


def test_get_active_path(tmp_models_dir):
    (tmp_models_dir / "ggml-base.bin").write_bytes(b"x")
    models_store.set_active("ggml-base.bin")
    p = models_store.get_active_path()
    assert p is not None
    assert p.name == "ggml-base.bin"


def test_remove_deletes_file_and_clears_active_if_active(tmp_models_dir):
    (tmp_models_dir / "ggml-base.bin").write_bytes(b"x")
    models_store.set_active("ggml-base.bin")
    models_store.remove("ggml-base.bin")
    assert not (tmp_models_dir / "ggml-base.bin").exists()
    assert models_store.get_active() is None


def test_remove_keeps_active_if_removing_other(tmp_models_dir):
    (tmp_models_dir / "ggml-base.bin").write_bytes(b"x")
    (tmp_models_dir / "ggml-tiny.bin").write_bytes(b"x")
    models_store.set_active("ggml-base.bin")
    models_store.remove("ggml-tiny.bin")
    assert models_store.get_active() == "ggml-base.bin"


def test_known_models_metadata():
    """KNOWN_MODELS exposes a dict with size, hf_url, sha256 per model."""
    for name in ("ggml-tiny.bin", "ggml-base.bin", "ggml-small.bin", "ggml-medium.bin"):
        assert name in models_store.KNOWN_MODELS
        meta = models_store.KNOWN_MODELS[name]
        assert "size_bytes" in meta
        assert "hf_url" in meta
        assert meta["hf_url"].startswith("https://huggingface.co/ggerganov/whisper.cpp")
