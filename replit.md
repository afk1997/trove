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
- `tests/` — pytest suite (418+ tests, 1 deselected on this machine; see Commands).
- `routes/api_v1.py` — stable JSON `/api/v1` blueprint (jobs, transcripts,
  models). Wraps the same JobManager / TranscribeJobManager / models_store
  as the HTML routes, exposed for the CLI + MCP server. Complex actions
  (download submit / resume / start transcribe) delegate to closures
  stashed on `app.extensions["trove.actions"]` by `create_app`.
- `cli.py` — `trove` CLI (entry point `trove`). Stdlib-only urllib client
  for `/api/v1`. Reads `TROVE_URL` (default `http://127.0.0.1:5000`) and
  `TROVE_TOKEN` from env.
- `mcp_server.py` — `trove-mcp` MCP server (entry point `trove-mcp`).
  Uses the official `mcp` SDK over stdio, talks to a running Trove HTTP
  server. Optional dep — `pip install 'trove[mcp]'`.

## Commands

- Run dev server: `python app.py` (workflow `Start application`).
- Rebuild CSS: `./tools/tailwindcss -c tailwind.config.js -i styles/input.css -o static/app.css --minify`
- Run tests: `python -m pytest --deselect tests/test_jobs.py::test_cancel_from_paused_removes_partial_files -q`
- CLI: `python cli.py <cmd>` (or `trove <cmd>` once installed). Examples:
  - `trove serve` — start the Flask server.
  - `trove fetch <url> --transcribe --wait` — download + auto-transcribe.
  - `trove list` / `trove transcripts` — list jobs.
  - `trove transcript <id> -f srt -o out.srt` — export a transcript.
  - `trove model-install ggml-base.bin --wait` — install + activate a model.
- MCP server: `trove-mcp` (stdio). Sample Claude Desktop config:
    ```json
    { "mcpServers": { "trove": { "command": "trove-mcp",
        "env": { "TROVE_URL": "http://127.0.0.1:5000" } } } }
    ```

## User preferences

- No HuggingFace logins, no auth tokens, no cloud APIs for transcription
  or diarization. Everything must run locally.
- Visible bugs (CSS bleed-throughs, focus rings) are high priority.
- Heavy ML deps (PyTorch via resemblyzer, etc.) ship by default but
  the *features* that use them must stay runtime-feature-flagged
  (e.g. `TROVE_DIARIZATION=on`) so the user opts into the cost, not
  the install.

## Recent changes

- 2026-05-03: added stable `/api/v1` JSON API + `trove` CLI + `trove-mcp`
  MCP server. Existing HTML endpoints unchanged. See
  `routes/api_v1.py`, `cli.py`, `mcp_server.py`.
- v3.1 (2026-05-02): bug fixes + floating left-rail video PiP +
  optional diarization (Resemblyzer + silero-vad) + comprehensive help
  panel + first-visit toast. See
  `docs/superpowers/plans/2026-05-03-trove-transcript-v3.1-plan.md`.
