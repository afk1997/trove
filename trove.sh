#!/bin/bash
set -e
cd "$(dirname "$0")"

# Pick a Python ≥ 3.10 — yt-dlp's master branch (which we install for current
# YouTube extractors) drops 3.9 support.
PYTHON_BIN=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    ver=$("$cand" -c 'import sys; print(sys.version_info[0]*100 + sys.version_info[1])' 2>/dev/null || echo 0)
    if [ "$ver" -ge 310 ]; then PYTHON_BIN="$cand"; break; fi
  fi
done

# Check prerequisites
missing=""
[ -z "$PYTHON_BIN" ] && missing="$missing python@3.13"
command -v ffmpeg >/dev/null 2>&1 || missing="$missing ffmpeg"

if [ -n "$missing" ]; then
  echo "Missing required tools:$missing"
  if command -v brew >/dev/null 2>&1; then echo "Install with:  brew install$missing"
  elif command -v apt >/dev/null 2>&1; then echo "Install with:  sudo apt install$missing"
  else echo "Please install:$missing"; fi
  exit 1
fi

# Python venv (rebuilt if it points at an older interpreter)
if [ -d "venv" ]; then
  cur_ver=$(./venv/bin/python -c 'import sys; print(sys.version_info[0]*100 + sys.version_info[1])' 2>/dev/null || echo 0)
  if [ "$cur_ver" -lt 310 ]; then
    echo "Existing venv is on Python <3.10; rebuilding with $PYTHON_BIN..."
    rm -rf venv
  fi
fi
if [ ! -d "venv" ]; then
  echo "Setting up virtual environment with $PYTHON_BIN..."
  "$PYTHON_BIN" -m venv venv
fi
# shellcheck source=/dev/null
source venv/bin/activate
pip install -q -U pip wheel >/dev/null
# Force-reinstall yt-dlp from master each run — extractors break weekly.
pip install -q -U --force-reinstall https://github.com/yt-dlp/yt-dlp/archive/master.tar.gz >/dev/null
pip install -q flask pytest >/dev/null

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
