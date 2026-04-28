# Trove

**Save things you care about.**

A self-hosted, browser-based downloader for video and audio from YouTube, TikTok, Instagram, Vimeo, and ~1000 other sites — powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [ffmpeg](https://ffmpeg.org/).

## Quick start

```bash
brew install yt-dlp ffmpeg    # macOS — or apt install ffmpeg && pip install yt-dlp
git clone https://github.com/afk1997/trove.git
cd trove
./trove.sh
```

Open **http://localhost:8899**.

Or with Docker:

```bash
docker build -t trove . && docker run -p 8899:8899 trove
```

## Status

Phase 1 in progress — see `docs/superpowers/specs/2026-04-28-trove-phase-1-design.md`.

## License

MIT. See [LICENSE](LICENSE).

---

Originally based on [averygan/reclip](https://github.com/averygan/reclip) (MIT). Substantially rewritten and rebranded as Trove in 2026.
