# Trove

**Save things you care about.**

A self-hosted, browser-based downloader for video and audio from YouTube, TikTok, Instagram, Vimeo, and ~1000 other sites — powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [ffmpeg](https://ffmpeg.org/).

- One paste box, one click — videos save to your device.
- Bulk paste, MP4/MP3 toggle, quality picker.
- Mobile-friendly, dark mode included.
- Single Python process, single Docker container, no Node.js.

## Quick start

```bash
brew install yt-dlp ffmpeg     # macOS — or apt install ffmpeg && pip install yt-dlp
git clone https://github.com/afk1997/trove.git
cd trove
./trove.sh
```

Open **http://localhost:8899**.

Or with Docker:

```bash
docker build -t trove .
docker run -p 8899:8899 -e HOST=0.0.0.0 trove
```

*The `-e HOST=0.0.0.0` is required for Docker port-forwarding. For LAN/internet exposure, also set `TROVE_TOKEN` — see below.*

## Configuration (env vars)

| Variable | Default | What it does |
|---|---|---|
| `HOST` | `127.0.0.1` | Bind address. Set to `0.0.0.0` only with a token. |
| `PORT` | `8899` | TCP port. |
| `TROVE_TOKEN` | *(unset)* | When set, every `/api/*` request must send `Authorization: Bearer <token>`. |
| `TROVE_COOKIES_FROM_BROWSER` | *(unset)* | One of `safari\|chrome\|firefox\|brave\|edge`. Required for YouTube right now (Google blocks cookieless yt-dlp). |
| `TROVE_JOB_TTL_SECONDS` | `3600` | How long completed jobs (and their files) linger before being swept. |
| `TROVE_MAX_WORKERS` | `4` | Concurrent downloads. Excess returns HTTP 503. |
| `TROVE_RATE_LIMIT` | `30` | Requests per minute per IP. Set to `0` to disable. |

## Exposing to LAN or the internet

The defaults assume **localhost only**. To expose Trove safely:

1. Set a token: `export TROVE_TOKEN=$(openssl rand -hex 32)`
2. Set host: `export HOST=0.0.0.0`
3. Run behind a reverse proxy that adds HTTPS (Caddy, nginx, fly.io, etc.).

Without `TROVE_TOKEN`, anyone who can reach the port can download.

## YouTube and cookies

YouTube currently blocks `yt-dlp` connections that don't carry a real browser cookie. To download from YouTube, set:

```bash
export TROVE_COOKIES_FROM_BROWSER=safari   # or chrome / firefox / brave / edge
./trove.sh
```

The browser must be installed on the host and have an active YouTube session.

## Stack

- **Backend:** Python 3.12 + Flask
- **Frontend:** htmx 2 + Alpine.js 3 + Tailwind CSS (standalone CLI, no Node at runtime)
- **Engine:** yt-dlp + ffmpeg

## Disclaimer

This tool is for personal use. Respect copyright laws and the terms of service of platforms you download from.

## License

MIT. See [LICENSE](LICENSE).

---

Originally based on [averygan/reclip](https://github.com/averygan/reclip) (MIT). Substantially rewritten and rebranded as Trove in 2026.
