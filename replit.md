# trove

A self-hosted Flask media downloader powered by yt-dlp + ffmpeg, with a
local whisper.cpp-based transcript editor.

## Project structure

- `app.py` — Flask app + worker threads (download jobs, transcribe jobs).
- `transcriber.py` — whisper.cpp wrapper (`run_transcribe`, `write_artifacts`,
  `apply_speakers` for diarization-aware regrouping).
- `diarizer.py` — local diarization (silero-vad → resemblyzer
  embeddings → sklearn agglomerative clustering). The deps
  (resemblyzer + silero-vad + scikit-learn, ~1.3GB on Linux incl.
  PyTorch+CUDA wheels) ship by default in `requirements.txt` /
  `pyproject.toml [project] dependencies`. The *feature* is still
  gated at runtime behind `TROVE_DIARIZATION` env var (default off)
  so plain transcribe runs don't pay the model-load cost.
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
- Heavy ML deps (PyTorch via resemblyzer, etc.) ship by default but
  the *features* that use them must stay runtime-feature-flagged
  (e.g. `TROVE_DIARIZATION=on`) so the user opts into the cost, not
  the install.

## Recent changes

- v3.1 (2026-05-02): bug fixes + floating left-rail video PiP +
  optional diarization (Resemblyzer + silero-vad) + comprehensive help
  panel + first-visit toast. See
  `docs/superpowers/plans/2026-05-03-trove-transcript-v3.1-plan.md`.
