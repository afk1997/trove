# syntax=docker/dockerfile:1

# Stage 1: build CSS with Tailwind standalone CLI
FROM debian:bookworm-slim AS builder
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY tailwind.config.js ./
COPY styles/ ./styles/
COPY templates/ ./templates/
RUN set -eux; \
    case "$TARGETARCH" in \
      arm64) URL=https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-arm64 ;; \
      amd64) URL=https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-x64 ;; \
      *) echo "unsupported arch: $TARGETARCH"; exit 1 ;; \
    esac; \
    curl -sSL "$URL" -o /usr/local/bin/tailwindcss && chmod +x /usr/local/bin/tailwindcss
RUN mkdir -p static && \
    /usr/local/bin/tailwindcss -c tailwind.config.js -i styles/input.css -o static/app.css --minify

# Stage 2: runtime
FROM python:3.12-slim
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 trove
WORKDIR /app
COPY requirements.txt .
# requirements.txt installs yt-dlp from its master branch (current YouTube extractors).
RUN pip install --no-cache-dir -r requirements.txt

# Persist the whisper model cache across container restarts.
# Users wanting explicit control can bind-mount: -v ./models:/app/models
VOLUME /app/models

COPY *.py ./
COPY templates/ ./templates/
COPY static/ ./static/
COPY --from=builder /build/static/app.css ./static/app.css
RUN mkdir -p downloads && chown -R trove:trove /app
USER trove
EXPOSE 8899
ENV HOST=127.0.0.1
ENV PORT=8899
CMD ["python", "app.py"]
