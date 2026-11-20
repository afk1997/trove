import io
import json
import shutil
import subprocess

import pytest

import app as app_module
from mp4 import prepare_download


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "DOWNLOAD_DIR", tmp_path)
    monkeypatch.delenv("TROVE_TOKEN", raising=False)
    return app_module.create_app().test_client()


@pytest.fixture
def legacy_video(tmp_path):
    if not all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe")):
        pytest.skip("requires ffmpeg and ffprobe")
    source = tmp_path / "original.avi"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=64x48",
                    "-f", "lavfi", "-i", "sine", "-t", "0.2", "-c:v", "mpeg4",
                    "-c:a", "pcm_s16le", str(source)], check=True)
    return source


def test_convert_uploaded_mpeg4_and_reuse_compatible_download(client, legacy_video, tmp_path):
    with legacy_video.open("rb") as source:
        response = client.post("/api/convert", data={"video": (source, "Vacation.mpeg4")})
    assert response.status_code == 200
    assert response.mimetype == "video/mp4"
    assert "Vacation - compatible.mp4" in response.headers["Content-Disposition"]
    native = tmp_path / "native.mp4"
    try:
        native.write_bytes(response.data)
    finally:
        response.close()
    info = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-of", "json", str(native),
    ]))
    video, audio = info["streams"]
    assert (video["codec_name"], video["pix_fmt"], audio["codec_name"]) == ("h264", "yuv420p", "aac")
    inode = native.stat().st_ino
    assert prepare_download(native) == native
    assert native.stat().st_ino == inode


def test_download_publishes_mp4_after_encoding(legacy_video):
    native = prepare_download(legacy_video)
    assert native == legacy_video.with_suffix(".mp4")
    assert native.stat().st_size > 0
    assert not legacy_video.exists()


def test_converter_rejects_unreadable_input(client):
    assert client.post("/api/convert", data={}).status_code == 400
    response = client.post("/api/convert", data={"video": (io.BytesIO(b"bad"), "broken.mp4")})
    assert response.status_code == 422


def test_converter_uses_api_auth(client, monkeypatch):
    monkeypatch.setenv("TROVE_TOKEN", "local-test")
    assert client.post("/api/convert").status_code == 401
