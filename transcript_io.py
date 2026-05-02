"""Single source of schema knowledge for transcript .words.json files.

Schema v2 adds editor support on top of the v1 whisper output:

    {
      "schema_version": 2,
      "language": "en",
      "duration": 12.0,
      "edited_at": null,
      "words": [
        {"idx": 0, "w": "hello", "original_w": "hello",
         "start": 0.0, "end": 0.42,
         "edited": false, "deleted": false}
      ],
      "segments": [
        {"start": 0.0, "end": 5.2, "text": "...",
         "word_idxs": [0,1,2,3], "speaker": null}
      ],
      "bookmarks": [
        {"id": "bm_abc1", "time": 12.34, "note": "key insight"}
      ]
    }

Authority rule:
- ``data["words"]`` is authoritative for word text/timing.
- ``data["segments"][i]["word_idxs"]`` is authoritative for paragraph
  membership and order. Segments are stable after migration; edits never
  re-derive paragraphs.

Public API:
- ``load(path)``  -> dict; auto-migrates v1 -> v2 on first read and writes
  a one-shot ``<base>.words.v1.json`` backup next to the file.
- ``save(path, data)`` -> writes atomically via tempfile + ``os.replace``.

Subsequent steps in the plan add ``apply_word_op``, ``apply_speaker``,
``find_replace``, ``regenerate_artifacts`` and bookmark helpers.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
from typing import Any


SCHEMA_VERSION = 2


class WordOpError(ValueError):
    """Raised when a word op cannot be applied (bad idx, bad op, etc.)."""


def load(path: str) -> dict:
    """Read a transcript JSON file, migrating v1 to v2 in place if needed.

    On a v1 file we:
      1. Copy the original bytes to ``<base>.words.v1.json`` (skipped if the
         backup already exists, so repeated loads stay idempotent).
      2. Mutate the parsed dict to schema v2 (see ``_migrate_v1_to_v2``).
      3. Atomically rewrite ``path`` with the v2 payload.

    Already-v2 files are returned untouched.
    """
    with open(path) as f:
        data = json.load(f)

    if data.get("schema_version") == SCHEMA_VERSION:
        return data

    # v1 file -> back up raw bytes once, then migrate + rewrite.
    backup_path = _v1_backup_path(path)
    if not os.path.exists(backup_path):
        # shutil.copy2 preserves metadata; both src + dst are the same FS.
        shutil.copy2(path, backup_path)

    _migrate_v1_to_v2(data)
    save(path, data)
    return data


def save(path: str, data: dict) -> None:
    """Atomically write ``data`` as JSON to ``path``.

    Mirrors the tempfile + ``os.replace`` pattern used by
    ``transcribe_jobs.JobStore._persist`` so a crash mid-write can never
    leave a half-written transcript on disk.
    """
    parent = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tio.", dir=parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _v1_backup_path(path: str) -> str:
    """``downloads/abc.words.json`` -> ``downloads/abc.words.v1.json``."""
    if path.endswith(".words.json"):
        return path[: -len(".words.json")] + ".words.v1.json"
    # Defensive fallback for unexpected extensions.
    base, ext = os.path.splitext(path)
    return f"{base}.v1{ext}"


def _migrate_v1_to_v2(data: dict) -> None:
    """Mutate ``data`` from schema v1 to schema v2 in place.

    Idempotent: re-running on a partially-migrated dict produces the same
    result. Order matters: words get ``idx`` first so segments can reference
    them by position. Segments in v1 are built by grouping consecutive flat
    words (see ``transcriber._build_segment``), so a positional cursor maps
    each segment's nested word list back to flat indices reliably -- even
    after a JSON round-trip has split the shared Python references.
    """
    words: list[dict[str, Any]] = data.get("words") or []
    for i, w in enumerate(words):
        w["idx"] = i
        w.setdefault("original_w", w.get("w", ""))
        w.setdefault("edited", False)
        w.setdefault("deleted", False)
    data["words"] = words

    segments: list[dict[str, Any]] = data.get("segments") or []
    cursor = 0
    for seg in segments:
        if "word_idxs" in seg:
            # Already migrated; just normalize defaults.
            cursor = max(cursor, (max(seg["word_idxs"]) + 1) if seg["word_idxs"] else cursor)
        else:
            nested = seg.pop("words", []) or []
            n = len(nested)
            seg["word_idxs"] = list(range(cursor, cursor + n))
            cursor += n
        seg.setdefault("speaker", None)
    data["segments"] = segments

    data.setdefault("bookmarks", [])
    data.setdefault("edited_at", None)
    data["schema_version"] = SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Word ops (TR-E2)
# ---------------------------------------------------------------------------

_WORD_OPS = ("set_text", "delete", "insert_after", "merge_next")


def apply_word_op(data: dict, idx: int, op: str, **kw) -> dict:
    """Apply ``op`` to the word at ``idx`` in-place; return that word's dict.

    Supported ops (kwargs in parens):
      - ``set_text`` (w) -- update text; ``edited`` tracks ``w != original_w``.
      - ``delete``       -- mark ``deleted=True``; ``word_idxs`` is preserved
                            so paragraph membership stays stable. The renderer
                            filters deleted words.
      - ``insert_after`` (w) -- append a new user-authored word right after
                                ``idx`` in that word's segment. The new word
                                inherits the anchor's ``end`` as a
                                zero-duration timestamp and gets a fresh,
                                higher idx.
      - ``merge_next``   -- absorb the next non-deleted peer word in the
                            anchor's segment: this word's text + " " + peer's
                            text, end = peer's end, peer marked deleted.

    Returns the (possibly newly-created) word dict that the UI should re-render.
    Raises ``WordOpError`` for unknown ops or out-of-range / invalid targets.
    """
    if op not in _WORD_OPS:
        raise WordOpError(f"unknown op: {op!r}")

    words = data.get("words") or []
    if not isinstance(idx, int) or idx < 0 or idx >= len(words):
        raise WordOpError(f"word idx out of range: {idx}")

    anchor = words[idx]
    if anchor.get("deleted"):
        raise WordOpError(f"word {idx} is deleted")

    if op == "set_text":
        new_text = _require_str(kw, "w")
        anchor["w"] = new_text
        anchor["edited"] = new_text != anchor.get("original_w", "")
        return anchor

    if op == "delete":
        anchor["deleted"] = True
        anchor["edited"] = True
        return anchor

    if op == "insert_after":
        new_text = _require_str(kw, "w")
        seg = _segment_of(data, idx)
        if seg is None:
            raise WordOpError(f"word {idx} is not attached to any segment")
        new_idx = max((w["idx"] for w in words), default=-1) + 1
        anchor_end = float(anchor.get("end", 0.0))
        new_word = {
            "idx": new_idx,
            "w": new_text,
            "original_w": new_text,
            "start": anchor_end,
            "end": anchor_end,
            "edited": False,
            "deleted": False,
        }
        words.append(new_word)
        # Splice into the segment immediately after the anchor.
        ids = seg["word_idxs"]
        ids.insert(ids.index(idx) + 1, new_idx)
        return new_word

    if op == "merge_next":
        seg = _segment_of(data, idx)
        if seg is None:
            raise WordOpError(f"word {idx} is not attached to any segment")
        next_idx = _next_visible_in_segment(seg, words, idx)
        if next_idx is None:
            raise WordOpError(f"word {idx} has no following word to merge")
        peer = words[next_idx]
        anchor["w"] = f"{anchor.get('w', '')}{peer.get('w', '')}"
        anchor["end"] = peer.get("end", anchor.get("end", 0.0))
        anchor["edited"] = anchor["w"] != anchor.get("original_w", "")
        peer["deleted"] = True
        peer["edited"] = True
        return anchor

    raise WordOpError(f"unhandled op: {op!r}")  # pragma: no cover


def _require_str(kw: dict, key: str) -> str:
    if key not in kw or not isinstance(kw[key], str):
        raise WordOpError(f"op requires string {key!r}")
    return kw[key]


def next_visible_word_idx(data: dict, idx: int) -> int | None:
    """Return the idx of the next non-deleted word in ``idx``'s segment, or None.

    Public helper so endpoint code (e.g. merge_next) can capture the peer
    word's idx *before* applying an op that marks it deleted.
    """
    seg = _segment_of(data, idx)
    if seg is None:
        return None
    return _next_visible_in_segment(seg, data.get("words") or [], idx)


def _segment_of(data: dict, idx: int) -> dict | None:
    for seg in data.get("segments") or []:
        if idx in seg.get("word_idxs", []):
            return seg
    return None


def _next_visible_in_segment(seg: dict, words: list, idx: int) -> int | None:
    ids = seg.get("word_idxs", [])
    try:
        pos = ids.index(idx)
    except ValueError:
        return None
    for j in ids[pos + 1:]:
        if 0 <= j < len(words) and not words[j].get("deleted"):
            return j
    return None


# ---------------------------------------------------------------------------
# Artifact regeneration (TR-E3)
# ---------------------------------------------------------------------------


def render_segment_text(seg: dict, words: list) -> str:
    """Join the visible (non-deleted) words for a segment into display text.

    Whisper emits punctuation glued to the preceding token (e.g. ``"world."``
    or ``" ,"``) so we just space-join: that mirrors what the on-screen
    renderer shows and what the v1 .txt export contained.
    """
    parts = []
    for i in seg.get("word_idxs", []):
        if 0 <= i < len(words) and not words[i].get("deleted"):
            parts.append(words[i].get("w", ""))
    return " ".join(parts).strip()


def regenerate_artifacts(data: dict, base_path: str) -> None:
    """Rewrite ``base_path.txt`` / ``.srt`` / ``.vtt`` from the current edits.

    Called after any mutation to keep on-disk exports in sync with the v2
    transcript JSON. Segment timestamps come straight from the migration --
    edits never re-derive paragraphs -- but each segment's text is rebuilt
    from the live words array so deletes/inserts/text changes are reflected.
    """
    rendered = []
    for seg in data.get("segments") or []:
        text = render_segment_text(seg, data.get("words") or [])
        rendered.append((float(seg.get("start", 0.0)), float(seg.get("end", 0.0)), text))

    txt = "\n\n".join(t for _, _, t in rendered if t)
    with open(base_path + ".txt", "w") as f:
        f.write(txt + ("\n" if txt and not txt.endswith("\n") else ""))

    with open(base_path + ".srt", "w") as f:
        n = 0
        for start, end, text in rendered:
            if not text:
                continue
            n += 1
            f.write(f"{n}\n")
            f.write(f"{_format_timestamp(start, srt=True)} --> {_format_timestamp(end, srt=True)}\n")
            f.write(text + "\n\n")

    with open(base_path + ".vtt", "w") as f:
        f.write("WEBVTT\n\n")
        for start, end, text in rendered:
            if not text:
                continue
            f.write(f"{_format_timestamp(start, srt=False)} --> {_format_timestamp(end, srt=False)}\n")
            f.write(text + "\n\n")


# ---------------------------------------------------------------------------
# Find / replace (TR-E7)
# ---------------------------------------------------------------------------


def find_replace(data: dict, find: str, replace: str, *, case_sensitive: bool = True) -> dict:
    """Substring-replace ``find`` with ``replace`` across all visible words.

    Operates only on non-deleted words. A word is updated whenever ``find``
    appears anywhere in its current text. ``edited`` is set whenever the
    new text diverges from ``original_w`` (and cleared when it matches).

    Returns ``{"count": N, "indices": [..]}`` -- the indices the caller
    should re-render.
    """
    if not find:
        return {"count": 0, "indices": []}
    indices: list[int] = []
    for w in data.get("words") or []:
        if w.get("deleted"):
            continue
        text = w.get("w", "")
        if case_sensitive:
            if find not in text:
                continue
            new_text = text.replace(find, replace)
        else:
            if find.lower() not in text.lower():
                continue
            new_text = _ireplace(text, find, replace)
        if new_text == text:
            continue
        w["w"] = new_text
        w["edited"] = new_text != w.get("original_w", "")
        indices.append(w["idx"])
    return {"count": len(indices), "indices": indices}


def _ireplace(text: str, find: str, replace: str) -> str:
    """Case-insensitive str.replace preserving non-matched characters."""
    out: list[str] = []
    i = 0
    fl = len(find)
    needle_lower = find.lower()
    text_lower = text.lower()
    while True:
        j = text_lower.find(needle_lower, i)
        if j < 0:
            out.append(text[i:])
            break
        out.append(text[i:j])
        out.append(replace)
        i = j + fl
    return "".join(out)


# ---------------------------------------------------------------------------
# Speaker labels (TR-E10)
# ---------------------------------------------------------------------------


def apply_speaker(data: dict, seg_idx: int, speaker: str | None, *, propagate: bool = True) -> list[int]:
    """Set ``segments[seg_idx].speaker``; return list of changed seg indices.

    When ``propagate`` is true (the default), the new speaker also fills in
    every following segment whose current ``speaker`` is ``None``, stopping
    at the first segment with a non-null speaker.
    """
    segments = data.get("segments") or []
    if seg_idx < 0 or seg_idx >= len(segments):
        raise ValueError(f"segment idx out of range: {seg_idx}")
    new_val = speaker or None
    changed: list[int] = []
    if segments[seg_idx].get("speaker") != new_val:
        segments[seg_idx]["speaker"] = new_val
        changed.append(seg_idx)
    if propagate and new_val is not None:
        for j in range(seg_idx + 1, len(segments)):
            if segments[j].get("speaker") is None:
                segments[j]["speaker"] = new_val
                changed.append(j)
            else:
                break
    return changed


# ---------------------------------------------------------------------------
# Bookmarks (TR-E11)
# ---------------------------------------------------------------------------


def add_bookmark(data: dict, time: float, note: str = "") -> dict:
    """Append a bookmark with a fresh stable id; keep the list sorted by time."""
    bm = {
        "id": "bm_" + secrets.token_hex(6),
        "time": float(time),
        "note": str(note or ""),
    }
    bms = data.setdefault("bookmarks", [])
    bms.append(bm)
    bms.sort(key=lambda b: b.get("time", 0.0))
    return bm


def update_bookmark(data: dict, bm_id: str, *, time: float | None = None, note: str | None = None) -> dict | None:
    """Update one bookmark's time / note. Returns the updated dict or None."""
    bms = data.get("bookmarks") or []
    for bm in bms:
        if bm.get("id") == bm_id:
            if time is not None:
                bm["time"] = float(time)
            if note is not None:
                bm["note"] = str(note)
            bms.sort(key=lambda b: b.get("time", 0.0))
            return bm
    return None


def delete_bookmark(data: dict, bm_id: str) -> bool:
    """Remove the bookmark with this id. Returns True iff something was removed."""
    bms = data.get("bookmarks") or []
    for i, bm in enumerate(bms):
        if bm.get("id") == bm_id:
            del bms[i]
            return True
    return False


def _format_timestamp(seconds: float, *, srt: bool) -> str:
    """SRT uses ``,`` as decimal sep; VTT uses ``.``."""
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    sep = "," if srt else "."
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"
