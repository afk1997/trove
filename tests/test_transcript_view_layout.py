"""Structural assertions on the rendered v4 transcript page.

These don't assert visual correctness — that's manual QA — but they
lock down the markup contract so that the layout we ship can't silently
regress to the v3 three-sticky-bars + floating-video shape.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import app as app_mod
import transcribe_jobs
from jobs import Job, JobStatus


@pytest.fixture
def client_with_done_transcript(tmp_path, monkeypatch):
    """Spin up an app pointed at tmp_path, with one DONE parent job and
    one DONE transcribe job whose words.json contains two speakers and
    two bookmarks. Yields (test_client, transcribe_id)."""
    monkeypatch.delenv("TROVE_TOKEN", raising=False)
    monkeypatch.setenv("TROVE_RATE_LIMIT", "0")
    monkeypatch.setattr(app_mod, "DOWNLOAD_DIR", tmp_path)
    a = app_mod.create_app()

    media = tmp_path / "src.mp4"
    media.write_bytes(b"fake-media")
    jm = a.extensions["trove.jobs"]
    def _noop(j):
        j.file_path = str(media)
        j.filename = "src.mp4"
    parent_id = jm.submit(target=_noop, title="Test clip", url="https://x")
    while jm.get(parent_id).status not in (JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELLED):
        pass

    base = os.path.splitext(media)[0]
    import json
    payload = {
        "schema_version": 2,
        "language": "en",
        "duration": 90.0,
        "edited_at": None,
        "title": None,
        "highlights": [],
        "notes": [],
        "words": [
            {"idx": 0, "w": "Hello", "original_w": "Hello",
             "start": 1.0, "end": 1.5, "edited": False, "deleted": False},
            {"idx": 1, "w": "world", "original_w": "world",
             "start": 1.5, "end": 2.0, "edited": False, "deleted": False},
            {"idx": 2, "w": "Yes", "original_w": "Yes",
             "start": 5.0, "end": 5.5, "edited": False, "deleted": False},
        ],
        "segments": [
            {"start": 1.0, "end": 2.0, "text": "Hello world",
             "word_idxs": [0, 1], "speaker": "Speaker 1", "reviewed": False},
            {"start": 5.0, "end": 5.5, "text": "Yes",
             "word_idxs": [2], "speaker": "Speaker 2", "reviewed": False},
        ],
        "bookmarks": [
            {"id": "bm_a", "time": 14.0, "note": "setup question"},
            {"id": "bm_b", "time": 68.0, "note": "hours"},
        ],
    }
    Path(base + ".words.json").write_text(json.dumps(payload))

    tm = a.extensions["trove.transcribe"]
    def _target(tj, *, model_path):
        tj.duration_seconds = 90.0
        tj.language_detected = "en"
    tjid = tm.submit(parent_job_id=parent_id, model_path="ignored", target=_target)
    while tm.get(tjid).status not in (
        transcribe_jobs.TranscribeStatus.DONE,
        transcribe_jobs.TranscribeStatus.ERROR,
        transcribe_jobs.TranscribeStatus.CANCELLED,
    ):
        pass

    with a.test_client() as c:
        yield c, tjid


def test_renders_single_topbar(client_with_done_transcript):
    c, tjid = client_with_done_transcript
    rv = c.get(f"/transcript/{tjid}")
    assert rv.status_code == 200
    body = rv.data.decode()
    assert 't-topbar' in body, "v4 topbar must render"
    assert 't-doc-toolbar' not in body, "v3 toolbar zone must be removed"
    assert 't-player-bar' not in body, "v3 player bar zone must be removed"
    assert 't-sidebar-player' in body, "v4 sidebar player must render"


def test_renders_two_column_grid(client_with_done_transcript):
    c, tjid = client_with_done_transcript
    body = c.get(f"/transcript/{tjid}").data.decode()
    assert 't-grid' in body
    assert 't-doc-body' in body
    assert 't-sidebar' in body


def test_renders_sidebar_video_player_panels(client_with_done_transcript):
    c, tjid = client_with_done_transcript
    body = c.get(f"/transcript/{tjid}").data.decode()
    assert 't-sidebar-video' in body
    assert 't-sidebar-player' in body
    assert 't-sidebar-panel--speakers' in body
    assert 't-sidebar-panel--bookmarks' in body


def test_no_video_rail_state_machine(client_with_done_transcript):
    c, tjid = client_with_done_transcript
    body = c.get(f"/transcript/{tjid}").data.decode()
    assert 't-video-rail' not in body, "v3 floating video rail must be removed"
    assert 'data-state="floating"' not in body
    assert 'data-state="expanded"' not in body
    assert 't-video-show-btn' not in body
    assert 't-sidebar-video' in body, "v4 sidebar video must render instead"


def test_speakers_panel_lists_distinct_speakers(client_with_done_transcript):
    c, tjid = client_with_done_transcript
    body = c.get(f"/transcript/{tjid}").data.decode()
    assert 't-sidebar-panel--speakers' in body, "speakers panel must render"
    assert 't-sidebar-panel--bookmarks' in body, "bookmarks panel must render"
    speakers_block = body.split('t-sidebar-panel--speakers', 1)[1].split('t-sidebar-panel--bookmarks', 1)[0]
    assert 'Speaker 1' in speakers_block
    assert 'Speaker 2' in speakers_block


def test_bookmarks_panel_renders_sorted(client_with_done_transcript):
    c, tjid = client_with_done_transcript
    body = c.get(f"/transcript/{tjid}").data.decode()
    assert 't-sidebar-panel--bookmarks' in body, "bookmarks panel must render"
    bookmarks_block = body.split('t-sidebar-panel--bookmarks', 1)[1].split('</aside>', 1)[0]
    assert 'setup question' in bookmarks_block
    assert 'hours' in bookmarks_block
    # First bookmark (14s = 0:14) appears before the second (68s = 1:08)
    pos_a = bookmarks_block.find('setup question')
    pos_b = bookmarks_block.find('hours')
    assert pos_a < pos_b, "bookmarks must render sorted by time ascending"


def test_search_popover_present_no_inline_bars(client_with_done_transcript):
    c, tjid = client_with_done_transcript
    body = c.get(f"/transcript/{tjid}").data.decode()
    assert 't-search-popover' in body, "search popover must render"
    assert 't-tb-search-bar' not in body, "v3 toolbar search bar must be removed"
    assert 't-fr-bar' not in body, "v3 floating right search bar must be removed"
