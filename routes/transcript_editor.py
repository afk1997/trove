"""Blueprint: transcript editor mutation endpoints.

Owns every endpoint that reads or writes a transcript's `.words.json`
document — word edits, segment splits/merges, speaker labels,
bookmarks, highlights, notes, title, find/replace, reviewed flag,
and selection export. The transcript *view* (`GET /transcript/<id>`)
and the format export (`GET /api/transcribe/<id>/export.<fmt>`) live
in app.py because they need ``token_or_sig_required`` rather than the
strict ``token_required`` used here.

Concurrency
-----------
All mutations go through ``_txn_lock(base)`` so the load → apply →
save → regenerate-artifacts sequence is atomic per transcript.
``_txn_locks`` is a per-app dict (stored on app.extensions) so multiple
test apps in the same process don't share locks.
"""
from __future__ import annotations
import os
from threading import Lock

from flask import Blueprint, current_app, jsonify, render_template, request, Response

import time as _time
import transcribe_jobs
import transcript_io
from safety import token_required
from util import sanitize_filename


bp = Blueprint("transcript_editor", __name__)


# --- shared helpers -------------------------------------------------------

def _managers():
    """Return (transcribe_manager, job_manager) from current_app."""
    return (
        current_app.extensions["trove.transcribe"],
        current_app.extensions["trove.jobs"],
    )


def _resolve_paths(transcribe_id):
    """Return (tj, parent, base_path) or (None, None, None) for a 404."""
    transcribe_manager, job_manager = _managers()
    tj = transcribe_manager.get(transcribe_id)
    if tj is None or tj.status != transcribe_jobs.TranscribeStatus.DONE:
        return None, None, None
    parent = job_manager.get(tj.parent_job_id)
    if parent is None or not parent.file_path:
        return None, None, None
    base = os.path.splitext(parent.file_path)[0]
    if not os.path.exists(base + ".words.json"):
        return None, None, None
    return tj, parent, base


def _save_after_edit(data, base):
    """Persist + regenerate exports after any transcript mutation."""
    data["edited_at"] = _time.time()
    transcript_io.save(base + ".words.json", data)
    transcript_io.regenerate_artifacts(data, base)


def _txn_lock(base: str) -> Lock:
    locks = current_app.extensions["trove.txn_locks"]
    guard = current_app.extensions["trove.txn_locks_guard"]
    with guard:
        lock = locks.get(base)
        if lock is None:
            lock = Lock()
            locks[base] = lock
        return lock


def _render_segments(data, indices):
    parts = []
    for idx in indices:
        if 0 <= idx < len(data.get("segments") or []):
            parts.append(render_template(
                "partials/transcript_segment.html",
                seg=data["segments"][idx],
                seg_idx=idx,
                data=data,
            ))
    return "".join(parts)


# --- word edits -----------------------------------------------------------

@bp.patch("/api/transcribe/<transcribe_id>/word/<int:idx>")
@token_required
def word_set_text(transcribe_id, idx):
    tj, parent, base = _resolve_paths(transcribe_id)
    if tj is None:
        return "", 404
    text = request.form.get("w")
    if text is None:
        return jsonify({"error": "missing w"}), 400
    with _txn_lock(base):
        try:
            data = transcript_io.load(base + ".words.json")
            word = transcript_io.apply_word_op(data, idx, "set_text", w=text)
        except transcript_io.WordOpError as e:
            return jsonify({"error": str(e)}), 400
        _save_after_edit(data, base)
    return render_template("partials/transcript_word.html", w=word)


@bp.delete("/api/transcribe/<transcribe_id>/word/<int:idx>")
@token_required
def word_delete(transcribe_id, idx):
    tj, parent, base = _resolve_paths(transcribe_id)
    if tj is None:
        return "", 404
    with _txn_lock(base):
        try:
            data = transcript_io.load(base + ".words.json")
            word = transcript_io.apply_word_op(data, idx, "delete")
        except transcript_io.WordOpError as e:
            return jsonify({"error": str(e)}), 400
        _save_after_edit(data, base)
    return render_template("partials/transcript_word.html", w=word)


@bp.post("/api/transcribe/<transcribe_id>/word/<int:idx>/insert-after")
@token_required
def word_insert_after(transcribe_id, idx):
    tj, parent, base = _resolve_paths(transcribe_id)
    if tj is None:
        return "", 404
    text = request.form.get("w", "")
    with _txn_lock(base):
        try:
            data = transcript_io.load(base + ".words.json")
            new_word = transcript_io.apply_word_op(data, idx, "insert_after", w=text)
        except transcript_io.WordOpError as e:
            return jsonify({"error": str(e)}), 400
        _save_after_edit(data, base)
    return render_template("partials/transcript_word.html", w=new_word)


@bp.post("/api/transcribe/<transcribe_id>/word/<int:idx>/merge-next")
@token_required
def word_merge_next(transcribe_id, idx):
    tj, parent, base = _resolve_paths(transcribe_id)
    if tj is None:
        return "", 404
    with _txn_lock(base):
        try:
            data = transcript_io.load(base + ".words.json")
            # Capture the peer idx BEFORE the op marks it deleted, so we
            # know which span to swap out-of-band.
            peer_idx = transcript_io.next_visible_word_idx(data, idx)
            anchor = transcript_io.apply_word_op(data, idx, "merge_next")
        except transcript_io.WordOpError as e:
            return jsonify({"error": str(e)}), 400
        _save_after_edit(data, base)
        peer = data["words"][peer_idx] if peer_idx is not None else None
    primary = render_template("partials/transcript_word.html", w=anchor)
    if peer is None:
        return primary
    oob = render_template("partials/transcript_word.html", w=peer, oob=True)
    return primary + oob


# --- find / replace -------------------------------------------------------

@bp.post("/api/transcribe/<transcribe_id>/find-replace")
@token_required
def find_replace(transcribe_id):
    tj, parent, base = _resolve_paths(transcribe_id)
    if tj is None:
        return "", 404
    find = request.form.get("find", "")
    replace = request.form.get("replace", "")
    case_sensitive = request.form.get("case_sensitive") in ("1", "on", "true")
    if not find:
        return jsonify({"error": "missing find"}), 400
    with _txn_lock(base):
        data = transcript_io.load(base + ".words.json")
        result = transcript_io.find_replace(
            data, find, replace, case_sensitive=case_sensitive,
        )
        if result["count"]:
            _save_after_edit(data, base)
        fragments = {
            str(idx): render_template(
                "partials/transcript_word.html", w=data["words"][idx],
            )
            for idx in result["indices"]
        }
    return jsonify({"count": result["count"], "fragments": fragments})


# --- speaker labels -------------------------------------------------------

@bp.patch("/api/transcribe/<transcribe_id>/segment/<int:seg_idx>/speaker")
@token_required
def segment_speaker(transcribe_id, seg_idx):
    tj, parent, base = _resolve_paths(transcribe_id)
    if tj is None:
        return "", 404
    speaker = (request.form.get("speaker") or "").strip() or None
    propagate = request.form.get("propagate", "1") in ("1", "on", "true")
    with _txn_lock(base):
        data = transcript_io.load(base + ".words.json")
        try:
            changed = transcript_io.apply_speaker(
                data, seg_idx, speaker, propagate=propagate,
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if changed:
            _save_after_edit(data, base)
        out_parts = []
        for idx in changed:
            out_parts.append(render_template(
                "partials/transcript_segment.html",
                seg=data["segments"][idx],
                seg_idx=idx,
                data=data,
            ))
    return "".join(out_parts) or ("", 200)


# --- bookmarks ------------------------------------------------------------

@bp.post("/api/transcribe/<transcribe_id>/bookmark")
@token_required
def bookmark_create(transcribe_id):
    tj, parent, base = _resolve_paths(transcribe_id)
    if tj is None:
        return "", 404
    time_str = request.form.get("time")
    if time_str is None:
        return jsonify({"error": "missing time"}), 400
    try:
        time_f = float(time_str)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid time"}), 400
    note = request.form.get("note", "")
    with _txn_lock(base):
        data = transcript_io.load(base + ".words.json")
        bm = transcript_io.add_bookmark(data, time_f, note)
        _save_after_edit(data, base)
    return render_template("partials/transcript_bookmark.html", bm=bm)


@bp.patch("/api/transcribe/<transcribe_id>/bookmark/<bm_id>")
@token_required
def bookmark_update(transcribe_id, bm_id):
    tj, parent, base = _resolve_paths(transcribe_id)
    if tj is None:
        return "", 404
    kwargs = {}
    if "time" in request.form:
        try:
            kwargs["time"] = float(request.form["time"])
        except (TypeError, ValueError):
            return jsonify({"error": "invalid time"}), 400
    if "note" in request.form:
        kwargs["note"] = request.form["note"]
    with _txn_lock(base):
        data = transcript_io.load(base + ".words.json")
        bm = transcript_io.update_bookmark(data, bm_id, **kwargs)
        if bm is None:
            return "", 404
        _save_after_edit(data, base)
    return render_template("partials/transcript_bookmark.html", bm=bm)


@bp.delete("/api/transcribe/<transcribe_id>/bookmark/<bm_id>")
@token_required
def bookmark_delete(transcribe_id, bm_id):
    tj, parent, base = _resolve_paths(transcribe_id)
    if tj is None:
        return "", 404
    with _txn_lock(base):
        data = transcript_io.load(base + ".words.json")
        if not transcript_io.delete_bookmark(data, bm_id):
            return "", 404
        _save_after_edit(data, base)
    return "", 200


# --- transcript document endpoints ----------------------------------------

@bp.patch("/api/transcribe/<transcribe_id>/title")
@token_required
def transcript_title(transcribe_id):
    tj, parent, base = _resolve_paths(transcribe_id)
    if tj is None:
        return "", 404
    title = request.form.get("title")
    if title is None:
        return jsonify({"error": "missing title"}), 400
    with _txn_lock(base):
        data = transcript_io.load(base + ".words.json")
        stored = transcript_io.set_title(data, title)
        _save_after_edit(data, base)
    effective = stored or (parent.title or "untitled")
    return jsonify({"title": stored, "effective": effective})


@bp.post("/api/transcribe/<transcribe_id>/segment/<int:seg_idx>/split")
@token_required
def segment_split(transcribe_id, seg_idx):
    tj, parent, base = _resolve_paths(transcribe_id)
    if tj is None:
        return "", 404
    try:
        after = int(request.form.get("after_word_idx", ""))
    except (TypeError, ValueError):
        return jsonify({"error": "missing or invalid after_word_idx"}), 400
    with _txn_lock(base):
        data = transcript_io.load(base + ".words.json")
        try:
            left, right = transcript_io.split_segment_at_word(data, seg_idx, after)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        _save_after_edit(data, base)
        html = _render_segments(data, [left, right])
    return html


@bp.post("/api/transcribe/<transcribe_id>/segment/<int:seg_idx>/merge-prev")
@token_required
def segment_merge_prev(transcribe_id, seg_idx):
    tj, parent, base = _resolve_paths(transcribe_id)
    if tj is None:
        return "", 404
    with _txn_lock(base):
        data = transcript_io.load(base + ".words.json")
        try:
            merged = transcript_io.merge_segment_with_prev(data, seg_idx)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        _save_after_edit(data, base)
        html = _render_segments(data, [merged])
    return html


@bp.patch("/api/transcribe/<transcribe_id>/speaker-rename")
@token_required
def speaker_rename(transcribe_id):
    tj, parent, base = _resolve_paths(transcribe_id)
    if tj is None:
        return "", 404
    if "old" not in request.form or "new" not in request.form:
        return jsonify({"error": "missing old or new"}), 400
    old_raw = request.form.get("old", "")
    old = old_raw.strip() or None
    new = request.form.get("new", "")
    with _txn_lock(base):
        data = transcript_io.load(base + ".words.json")
        changed = transcript_io.rename_speaker(data, old, new)
        if changed:
            _save_after_edit(data, base)
        html = _render_segments(data, changed)
    return jsonify({"updated": changed, "html": html})


@bp.post("/api/transcribe/<transcribe_id>/highlight")
@token_required
def highlight_create(transcribe_id):
    tj, parent, base = _resolve_paths(transcribe_id)
    if tj is None:
        return "", 404
    try:
        start = int(request.form.get("word_idx_start", ""))
        end = int(request.form.get("word_idx_end", ""))
    except (TypeError, ValueError):
        return jsonify({"error": "missing word_idx_start / word_idx_end"}), 400
    with _txn_lock(base):
        data = transcript_io.load(base + ".words.json")
        try:
            h = transcript_io.add_highlight(data, start, end)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        _save_after_edit(data, base)
    return jsonify(h)


@bp.delete("/api/transcribe/<transcribe_id>/highlight/<h_id>")
@token_required
def highlight_delete(transcribe_id, h_id):
    tj, parent, base = _resolve_paths(transcribe_id)
    if tj is None:
        return "", 404
    with _txn_lock(base):
        data = transcript_io.load(base + ".words.json")
        if not transcript_io.delete_highlight(data, h_id):
            return "", 404
        _save_after_edit(data, base)
    return "", 200


@bp.post("/api/transcribe/<transcribe_id>/note")
@token_required
def note_create(transcribe_id):
    tj, parent, base = _resolve_paths(transcribe_id)
    if tj is None:
        return "", 404
    try:
        word_idx = int(request.form.get("word_idx", ""))
    except (TypeError, ValueError):
        return jsonify({"error": "missing word_idx"}), 400
    text = request.form.get("text", "")
    with _txn_lock(base):
        data = transcript_io.load(base + ".words.json")
        try:
            note = transcript_io.add_note(data, word_idx, text)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        _save_after_edit(data, base)
    return jsonify(note)


@bp.patch("/api/transcribe/<transcribe_id>/note/<n_id>")
@token_required
def note_update(transcribe_id, n_id):
    tj, parent, base = _resolve_paths(transcribe_id)
    if tj is None:
        return "", 404
    if "text" not in request.form:
        return jsonify({"error": "missing text"}), 400
    with _txn_lock(base):
        data = transcript_io.load(base + ".words.json")
        note = transcript_io.update_note(data, n_id, request.form["text"])
        if note is None:
            return "", 404
        _save_after_edit(data, base)
    return jsonify(note)


@bp.delete("/api/transcribe/<transcribe_id>/note/<n_id>")
@token_required
def note_delete(transcribe_id, n_id):
    tj, parent, base = _resolve_paths(transcribe_id)
    if tj is None:
        return "", 404
    with _txn_lock(base):
        data = transcript_io.load(base + ".words.json")
        if not transcript_io.delete_note(data, n_id):
            return "", 404
        _save_after_edit(data, base)
    return "", 200


@bp.patch("/api/transcribe/<transcribe_id>/segment/<int:seg_idx>/reviewed")
@token_required
def segment_reviewed(transcribe_id, seg_idx):
    tj, parent, base = _resolve_paths(transcribe_id)
    if tj is None:
        return "", 404
    raw = request.form.get("reviewed", "")
    reviewed = raw in ("1", "on", "true", "yes")
    with _txn_lock(base):
        data = transcript_io.load(base + ".words.json")
        try:
            changed = transcript_io.set_segment_reviewed(data, seg_idx, reviewed)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if changed:
            _save_after_edit(data, base)
    return jsonify({"seg_idx": seg_idx, "reviewed": reviewed})


@bp.post("/api/transcribe/<transcribe_id>/export-selection")
@token_required
def export_selection(transcribe_id):
    tj, parent, base = _resolve_paths(transcribe_id)
    if tj is None:
        return "", 404
    try:
        start = int(request.form.get("word_idx_start", ""))
        end = int(request.form.get("word_idx_end", ""))
    except (TypeError, ValueError):
        return jsonify({"error": "missing word_idx_start / word_idx_end"}), 400
    with _txn_lock(base):
        data = transcript_io.load(base + ".words.json")
        words = data.get("words") or []
        if start < 0 or end >= len(words) or start > end:
            return jsonify({"error": "invalid range"}), 400
        # Walk segments; emit any segment that overlaps [start..end] as
        # "[hh:mm:ss] <words>". Words outside the range are skipped.
        chunks = []
        for seg in data.get("segments") or []:
            ids = [j for j in seg.get("word_idxs", [])
                   if start <= j <= end and not words[j].get("deleted")]
            if not ids:
                continue
            ts = transcript_io._format_timestamp(float(seg.get("start", 0.0)), srt=False)
            text = transcript_io._join_word_tokens(
                words[j].get("w", "") for j in ids
            ).strip()
            if text:
                chunks.append(f"[{ts}] {text}")
        body = "\n\n".join(chunks) + ("\n" if chunks else "")
    download_name = sanitize_filename((parent.title or "selection") + " (selection)", ".txt")
    return Response(
        body,
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )
