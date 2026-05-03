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
        # v2 -> v2.1 backfill: the v3 redesign added optional title /
        # highlights / notes / reviewed fields. Old v2 files lack them;
        # patch them in on read so callers always see the full shape.
        # Persisted lazily on the next save().
        if _backfill_v21_defaults(data):
            save(path, data)
        return data

    # v1 file -> back up raw bytes once, then migrate + rewrite.
    backup_path = _v1_backup_path(path)
    if not os.path.exists(backup_path):
        # shutil.copy2 preserves metadata; both src + dst are the same FS.
        shutil.copy2(path, backup_path)

    _migrate_v1_to_v2(data)
    save(path, data)
    return data


def _backfill_v21_defaults(data: dict) -> bool:
    """Populate v2.1 fields on an already-v2 doc; return True iff anything changed."""
    changed = False
    if "title" not in data:
        data["title"] = None
        changed = True
    if "highlights" not in data:
        data["highlights"] = []
        changed = True
    if "notes" not in data:
        data["notes"] = []
        changed = True
    for seg in data.get("segments") or []:
        if "reviewed" not in seg:
            seg["reviewed"] = False
            changed = True
    return changed


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
    # v2.1 (additive, no schema bump): document title, per-segment reviewed
    # flag, highlights and notes arrays. Defaults are picked so a freshly
    # migrated v1 doc renders identically to before the v3 redesign.
    data.setdefault("title", None)
    data.setdefault("highlights", [])
    data.setdefault("notes", [])
    for seg in segments:
        seg.setdefault("reviewed", False)
    data["schema_version"] = SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Word ops (TR-E2)
# ---------------------------------------------------------------------------

_WORD_OPS = ("set_text", "delete", "insert_after", "merge_next")


# Punctuation that should hug the previous word (no leading space).
# Whisper sometimes emits these as standalone tokens; naive
# `" ".join(words)` would produce "hello ." instead of "hello.".
_RIGHT_HUGS_LEFT = frozenset({
    ".", ",", "!", "?", ":", ";", "%", ")", "]", "}",
    "'s", "n't", "'re", "'ll", "'ve", "'d", "'m",
    "…", "”", "’", "»",
})

# Punctuation that should hug the following word (no trailing space).
_LEFT_HUGS_RIGHT = frozenset({
    "(", "[", "{", "$", "#", "@",
    "“", "‘", "«",
})


def join_word_text(left: str, right: str) -> str:
    """Concatenate two transcript word tokens with the right whitespace.

    Single source of truth for how transcript words combine. Used by
    every site that joins / merges word text so display, export, and
    structural edits all agree.

    Rules:
      * Empty operand → return the other (no leading/trailing space).
      * If `right` is closing punctuation (.,!?:;%)]}, possessive 's,
        contractions n't/'re/'ll/'ve/'d/'m, ellipsis, closing quote)
        → glue with no space:   "hello" + "."     -> "hello."
      * If `left` is opening punctuation (([{$#@, opening quote)
        → glue with no space:   "$"     + "100"   -> "$100"
      * Otherwise insert a single space: "hello" + "world" -> "hello world".

    This intentionally does NOT try to be a full natural-language joiner
    (it won't undo Whisper's existing inline punctuation, won't handle
    em-dashes, won't fix contractions whisper already glued). It just
    avoids the obvious "helloworld" / "hello ." failure modes when
    standalone tokens get joined.
    """
    if not left:
        return right
    if not right:
        return left
    if right in _RIGHT_HUGS_LEFT:
        return left + right
    if left in _LEFT_HUGS_RIGHT:
        return left + right
    return left + " " + right


def _join_word_tokens(tokens) -> str:
    """Reduce an iterable of word strings via :func:`join_word_text`.

    Skips empty strings so deleted/blank words don't introduce double
    spaces. Returns the empty string for an empty input.

    Implementation note: we track the *previous raw token* separately
    from the running accumulator so the "$" + "100" -> "$100" rule
    fires on the previous token's identity, not on whether the whole
    accumulator happens to end with "$".
    """
    out = ""
    prev = ""
    for t in tokens:
        if not t:
            continue
        if not out:
            out = t
        else:
            # Use prev (the last raw token) as the left operand so the
            # opening-punctuation check matches the token, not a tail
            # substring of the accumulator. Then splice the joined pair
            # back onto the accumulator (minus prev, which was its tail).
            joined = join_word_text(prev, t)
            out = out[: len(out) - len(prev)] + joined
        prev = t
    return out


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
        anchor["w"] = join_word_text(anchor.get("w", ""), peer.get("w", ""))
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

    Uses :func:`join_word_text` so standalone punctuation tokens
    (".", ",", "$", "(", …) compose without spurious whitespace.
    """
    parts = []
    for i in seg.get("word_idxs", []):
        if 0 <= i < len(words) and not words[i].get("deleted"):
            parts.append(words[i].get("w", ""))
    return _join_word_tokens(parts).strip()


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

    def _atomic_write(path: str, body: str) -> None:
        # Mirror the tempfile + os.replace pattern used by save() so that
        # a concurrent export GET landing mid-write never reads a torn
        # file, and a crash mid-write leaves the prior version intact.
        parent = os.path.dirname(path) or "."
        fd, tmp = tempfile.mkstemp(prefix=".tio.", dir=parent)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(body)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    txt = "\n\n".join(t for _, _, t in rendered if t)
    txt_body = txt + ("\n" if txt and not txt.endswith("\n") else "")
    _atomic_write(base_path + ".txt", txt_body)

    srt_parts: list[str] = []
    n = 0
    for start, end, text in rendered:
        if not text:
            continue
        n += 1
        srt_parts.append(
            f"{n}\n{_format_timestamp(start, srt=True)} --> {_format_timestamp(end, srt=True)}\n{text}\n\n"
        )
    _atomic_write(base_path + ".srt", "".join(srt_parts))

    vtt_parts: list[str] = ["WEBVTT\n\n"]
    for start, end, text in rendered:
        if not text:
            continue
        vtt_parts.append(
            f"{_format_timestamp(start, srt=False)} --> {_format_timestamp(end, srt=False)}\n{text}\n\n"
        )
    _atomic_write(base_path + ".vtt", "".join(vtt_parts))


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


# ---------------------------------------------------------------------------
# Document title (TR-D series)
# ---------------------------------------------------------------------------


def set_title(data: dict, title: str | None) -> str | None:
    """Set ``data['title']`` (None / empty falls back to parent.title at render).

    Returns the stored value (None for empty input).
    """
    val = (title or "").strip() or None
    data["title"] = val
    return val


# ---------------------------------------------------------------------------
# Segment split / merge (TR-D)
# ---------------------------------------------------------------------------


def split_segment_at_word(data: dict, seg_idx: int, after_word_idx: int) -> tuple[int, int]:
    """Split ``segments[seg_idx]`` so that ``after_word_idx`` ends the first half.

    The new (right) segment inherits the original speaker; its ``start`` time
    is derived from its first word's ``start``. The left half keeps the same
    ``seg_idx``; the right half is inserted at ``seg_idx + 1`` and shifts
    every following segment's index by +1.

    **Review state is invalidated on split.** Both halves are marked
    ``reviewed=False`` regardless of the original value, because splitting
    a paragraph restructures its content and the human reviewer no longer
    has eyes on the new boundary. The user can re-mark either half as
    reviewed if they wish.

    Returns ``(left_idx, right_idx)``.

    Raises ``ValueError`` if the split point is invalid (out-of-range, last
    word in segment, or word not in this segment).
    """
    segments = data.get("segments") or []
    if seg_idx < 0 or seg_idx >= len(segments):
        raise ValueError(f"segment idx out of range: {seg_idx}")
    seg = segments[seg_idx]
    ids = seg.get("word_idxs", [])
    try:
        pos = ids.index(after_word_idx)
    except ValueError:
        raise ValueError(f"word {after_word_idx} not in segment {seg_idx}")
    if pos == len(ids) - 1:
        raise ValueError("cannot split after the last word in a segment")

    left_ids = ids[: pos + 1]
    right_ids = ids[pos + 1:]
    words = data.get("words") or []

    def _bound(ids_, key):
        for j in ids_:
            if 0 <= j < len(words) and not words[j].get("deleted"):
                v = words[j].get(key)
                if v is not None:
                    return float(v)
        return None

    left_start = _bound(left_ids, "start")
    if left_start is None:
        left_start = float(seg.get("start", 0.0))
    left_end_vals = [float(words[j].get("end", 0.0)) for j in left_ids
                     if 0 <= j < len(words) and not words[j].get("deleted")]
    left_end = max(left_end_vals) if left_end_vals else left_start

    right_start = _bound(right_ids, "start")
    if right_start is None:
        right_start = left_end
    right_end_vals = [float(words[j].get("end", 0.0)) for j in right_ids
                      if 0 <= j < len(words) and not words[j].get("deleted")]
    right_end = max(right_end_vals) if right_end_vals else float(seg.get("end", right_start))

    seg["word_idxs"] = left_ids
    seg["start"] = left_start
    seg["end"] = left_end
    seg["text"] = render_segment_text(seg, words)
    # Splitting restructures content, so any prior human review on the
    # original segment no longer applies to either half. See docstring.
    seg["reviewed"] = False

    new_seg = {
        "start": right_start,
        "end": right_end,
        "text": "",
        "word_idxs": right_ids,
        "speaker": seg.get("speaker"),
        "reviewed": False,  # see docstring: split invalidates review on both halves
    }
    new_seg["text"] = render_segment_text(new_seg, words)
    segments.insert(seg_idx + 1, new_seg)
    return seg_idx, seg_idx + 1


def merge_segment_with_prev(data: dict, seg_idx: int) -> int:
    """Merge ``segments[seg_idx]`` into the segment before it; return the merged idx.

    The merged segment keeps ``segments[seg_idx-1]``'s speaker (the earlier
    one wins). ``reviewed`` is True only if both halves were reviewed.

    Raises ``ValueError`` if ``seg_idx`` is 0 or out of range.
    """
    segments = data.get("segments") or []
    if seg_idx <= 0 or seg_idx >= len(segments):
        raise ValueError(f"cannot merge segment {seg_idx} with previous")
    cur = segments[seg_idx]
    prev = segments[seg_idx - 1]
    prev["word_idxs"] = list(prev.get("word_idxs", [])) + list(cur.get("word_idxs", []))
    prev["end"] = float(cur.get("end", prev.get("end", 0.0)))
    prev["reviewed"] = bool(prev.get("reviewed")) and bool(cur.get("reviewed"))
    prev["text"] = render_segment_text(prev, data.get("words") or [])
    del segments[seg_idx]
    return seg_idx - 1


# ---------------------------------------------------------------------------
# Global speaker rename (TR-D)
# ---------------------------------------------------------------------------


def rename_speaker(data: dict, old: str | None, new: str | None) -> list[int]:
    """Replace every occurrence of ``old`` speaker label with ``new``.

    Returns the list of segment indices whose speaker changed. ``new`` of
    empty / None clears the speaker on matched segments.
    """
    segments = data.get("segments") or []
    new_val = (new or "").strip() or None
    changed: list[int] = []
    for i, seg in enumerate(segments):
        if seg.get("speaker") == old:
            if seg.get("speaker") != new_val:
                seg["speaker"] = new_val
                changed.append(i)
    return changed


# ---------------------------------------------------------------------------
# Highlights (TR-D)
# ---------------------------------------------------------------------------


def add_highlight(data: dict, word_idx_start: int, word_idx_end: int) -> dict:
    """Append a highlight covering [start..end] inclusive; return the new dict.

    Raises ``ValueError`` for an inverted or out-of-range range.
    """
    n = len(data.get("words") or [])
    if word_idx_start < 0 or word_idx_end >= n or word_idx_start > word_idx_end:
        raise ValueError(
            f"invalid highlight range: [{word_idx_start}..{word_idx_end}] over {n} words"
        )
    h = {
        "id": "h_" + secrets.token_hex(6),
        "word_idx_start": int(word_idx_start),
        "word_idx_end": int(word_idx_end),
    }
    data.setdefault("highlights", []).append(h)
    return h


def delete_highlight(data: dict, h_id: str) -> bool:
    hs = data.get("highlights") or []
    for i, h in enumerate(hs):
        if h.get("id") == h_id:
            del hs[i]
            return True
    return False


# ---------------------------------------------------------------------------
# Notes (TR-D)
# ---------------------------------------------------------------------------


def add_note(data: dict, word_idx: int, text: str) -> dict:
    n = len(data.get("words") or [])
    if word_idx < 0 or word_idx >= n:
        raise ValueError(f"note word idx out of range: {word_idx}")
    note = {
        "id": "n_" + secrets.token_hex(6),
        "word_idx": int(word_idx),
        "text": str(text or ""),
    }
    data.setdefault("notes", []).append(note)
    return note


def update_note(data: dict, n_id: str, text: str) -> dict | None:
    for note in data.get("notes") or []:
        if note.get("id") == n_id:
            note["text"] = str(text or "")
            return note
    return None


def delete_note(data: dict, n_id: str) -> bool:
    notes = data.get("notes") or []
    for i, note in enumerate(notes):
        if note.get("id") == n_id:
            del notes[i]
            return True
    return False


# ---------------------------------------------------------------------------
# Per-segment reviewed flag (TR-D)
# ---------------------------------------------------------------------------


def set_segment_reviewed(data: dict, seg_idx: int, reviewed: bool) -> bool:
    segments = data.get("segments") or []
    if seg_idx < 0 or seg_idx >= len(segments):
        raise ValueError(f"segment idx out of range: {seg_idx}")
    new_val = bool(reviewed)
    if segments[seg_idx].get("reviewed") == new_val:
        return False
    segments[seg_idx]["reviewed"] = new_val
    return True


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
