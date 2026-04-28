#!/bin/bash
set -e
cd "$(dirname "$0")"

# Check prerequisites
missing=""
command -v python3 >/dev/null 2>&1 || missing="$missing python3"
command -v ffmpeg  >/dev/null 2>&1 || missing="$missing ffmpeg"

if [ -n "$missing" ]; then
  echo "Missing required tools:$missing"
  if command -v brew >/dev/null 2>&1; then echo "Install with:  brew install$missing"
  elif command -v apt >/dev/null 2>&1; then echo "Install with:  sudo apt install$missing"
  else echo "Please install:$missing"; fi
  exit 1
fi

# Python venv
if [ ! -d "venv" ]; then
  echo "Setting up virtual environment..."
  python3 -m venv venv
fi
# shellcheck source=/dev/null
source venv/bin/activate
pip install -q -U pip wheel >/dev/null
pip install -q -r requirements.txt >/dev/null
# Always update yt-dlp — its extractors break weekly.
pip install -q -U yt-dlp >/dev/null

# Tailwind binary
if [ ! -x tools/tailwindcss ]; then
  echo "Downloading Tailwind CSS standalone CLI..."
  mkdir -p tools
  OS=$(uname -s | tr '[:upper:]' '[:lower:]')
  ARCH=$(uname -m)
  case "$OS-$ARCH" in
    darwin-arm64)  URL=https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-macos-arm64 ;;
    darwin-x86_64) URL=https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-macos-x64 ;;
    linux-x86_64)  URL=https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-x64 ;;
    linux-aarch64) URL=https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-arm64 ;;
    *) echo "Unsupported platform: $OS-$ARCH"; exit 1 ;;
  esac
  curl -sSL "$URL" -o tools/tailwindcss
  chmod +x tools/tailwindcss
fi

# Build CSS
./tools/tailwindcss -c tailwind.config.js -i styles/input.css -o static/app.css --minify >/dev/null

PORT="${PORT:-8899}"
HOST="${HOST:-127.0.0.1}"
export PORT HOST
echo ""
echo "  Trove is running at http://$HOST:$PORT"
echo ""
exec python3 app.py
