# trove

A self-hosted Flask media downloader powered by yt-dlp + ffmpeg, with a
local whisper.cpp-based transcript editor.

## Project structure

- `app.py` — Flask app + worker threads (download jobs, transcribe jobs).
- `transcriber.py` — whisper.cpp wrapper (`run_transcribe`, `write_artifacts`,
  `apply_speakers` for diarization-aware regrouping).
- `diarizer.py` — optional local diarization (silero-vad → resemblyzer
  embeddings → sklearn agglomerative clustering). Lazy-imports its heavy
  deps; gated behind `TROVE_DIARIZATION` env var (default off). Heavy
  deps (~800MB incl. PyTorch) are NOT installed by default.
- `transcript_io.py` — atomic JSON sidecar I/O for the transcript editor.
- `templates/transcript.html` — single-file transcript editor (CSP-nonced
  inline JS, no second `<script>` tag allowed).
- `styles/input.css` → `static/app.css` — Tailwind standalone CLI build.
- `tests/` — pytest suite (321 tests, 8 skipped when sklearn missing).

## Commands

- Run dev server: `python app.py` (workflow `Start application`).
- Rebuild CSS: `./tools/tailwindcss -c tailwind.config.js -i styles/input.css -o static/app.css --minify`
- Run tests: `python -m pytest --deselect tests/test_jobs.py::test_cancel_from_paused_removes_partial_files -q`

## User preferences

- No HuggingFace logins, no auth tokens, no cloud APIs for transcription
  or diarization. Everything must run locally.
- Visible bugs (CSS bleed-throughs, focus rings) are high priority.
- Heavy ML deps (PyTorch, etc.) are opt-in only — must be feature-flagged.

## Recent changes

- v3.1 (2026-05-02): bug fixes + floating left-rail video PiP +
  optional diarization (Resemblyzer + silero-vad) + comprehensive help
  panel + first-visit toast. See
  `docs/superpowers/plans/2026-05-03-trove-transcript-v3.1-plan.md`.
