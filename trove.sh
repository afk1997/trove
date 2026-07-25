#!/usr/bin/env bash
#
# trove.sh — bootstrap and launch Trove locally.
#
# macOS users can double-click start-trove.command instead of using this
# directly; it is a thin wrapper around this script.
#
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# ---------------------------------------------------------------- options ---
FULL=0
OPEN_BROWSER=1

usage() {
  cat <<'EOF'
usage: ./trove.sh [options]

  (no options)   install the core stack (downloader + transcription) and serve
  --full         also install diarization / speaker labels.
                 Pulls PyTorch transitively — roughly 1.3GB, one time.
  --no-open      do not open a browser once the server is up
  -h, --help     show this message

environment:
  HOST           bind address                    (default 127.0.0.1)
  PORT           TCP port                        (default 8899)
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --full)     FULL=1 ;;
    --no-open)  OPEN_BROWSER=0 ;;
    -h|--help)  usage; exit 0 ;;
    *)          printf 'unknown option: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

# ---------------------------------------------------------------- output ----
if [ -t 1 ]; then
  B=$(printf '\033[1m'); D=$(printf '\033[2m'); R=$(printf '\033[31m')
  G=$(printf '\033[32m'); Y=$(printf '\033[33m'); X=$(printf '\033[0m')
else
  B=''; D=''; R=''; G=''; Y=''; X=''
fi

ok()   { printf '  %s✓%s %s\n' "$G" "$X" "$1"; }
warn() { printf '  %s!%s %s\n' "$Y" "$X" "$1"; }
info() { printf '  %s·%s %s\n' "$D" "$X" "$1"; }
die() {
  printf '  %s✗%s %s\n' "$R" "$X" "$1" >&2
  shift
  for line in "$@"; do printf '      %s\n' "$line" >&2; done
  exit 1
}

printf '\n%sTrove%s — checking your machine\n\n' "$B" "$X"

# ------------------------------------------------------------- preflight ----
# Python. yt-dlp raised its minimum recommended interpreter to 3.11 (3.10 goes
# EOL in October 2026) and pyproject.toml already declares requires-python
# >=3.11, so 3.11 is the floor. The probe list runs high-to-low and is padded
# with versions that do not exist yet on purpose: this script previously
# stopped at 3.13 and broke outright the moment Homebrew moved to 3.14.
PYTHON_BIN=''
PYTHON_VER=''
for cand in python3.17 python3.16 python3.15 python3.14 python3.13 python3.12 python3.11 python3; do
  command -v "$cand" >/dev/null 2>&1 || continue
  v=$("$cand" -c 'import sys; print(sys.version_info[0]*100 + sys.version_info[1])' 2>/dev/null || echo 0)
  if [ "$v" -ge 311 ]; then
    PYTHON_BIN="$cand"
    PYTHON_VER=$("$cand" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')
    break
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  if command -v brew >/dev/null 2>&1; then
    die "no Python 3.11 or newer found." "install one with:  brew install python@3.14"
  else
    die "no Python 3.11 or newer found." \
        "macOS:          brew install python@3.14" \
        "Debian/Ubuntu:  sudo apt install python3.12 python3.12-venv"
  fi
fi
ok "python $PYTHON_VER  ${D}($(command -v "$PYTHON_BIN"))${X}"

# ffmpeg — needed to merge video+audio streams and to extract audio for whisper.
if command -v ffmpeg >/dev/null 2>&1; then
  ok "ffmpeg $(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}')"
elif command -v brew >/dev/null 2>&1 && [ -t 0 ]; then
  warn "ffmpeg not found — required to merge streams and extract audio"
  printf '      install it with Homebrew now? [y/N] '
  read -r reply || reply=''
  case "$reply" in
    [yY]*) brew install ffmpeg || die "brew install ffmpeg failed." ;;
    *)     die "ffmpeg is required." "install with:  brew install ffmpeg" ;;
  esac
  ok "ffmpeg installed"
else
  die "ffmpeg not found." \
      "macOS:          brew install ffmpeg" \
      "Debian/Ubuntu:  sudo apt install ffmpeg"
fi

# ------------------------------------------------------------------ venv ----
# Probe the venv by actually executing its interpreter. A venv whose Python was
# uninstalled from under it (Homebrew upgrading 3.13 -> 3.14, say) leaves a
# dangling symlink that only fails at exec time — a version string check alone
# would not catch it.
VPY='venv/bin/python'
if [ -d venv ]; then
  if "$VPY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    ok "venv healthy"
  else
    warn "venv is broken or predates Python 3.11 — rebuilding it"
    rm -rf venv
  fi
fi
if [ ! -d venv ]; then
  info "creating venv with $PYTHON_BIN ..."
  "$PYTHON_BIN" -m venv venv
  ok "venv created"
fi

# ----------------------------------------------------------- dependencies ---
# yt-dlp is installed from the nightly channel with extras, which is upstream's
# own recommendation for regular users:
#   [default]   yt-dlp-ejs — solves YouTube's JS challenges. Without it YouTube
#               extraction is deprecated and formats go missing. This is the
#               single most important reason for the extras.
#   [curl-cffi] --impersonate, for sites that gate on TLS fingerprint.
#   [deno]      the Deno JS runtime, shipped as a wheel, so no Homebrew needed.
YTDLP_SPEC='yt-dlp[default,curl-cffi,deno]'
CORE_PKGS='flask>=3.0 psutil>=5.9 pywhispercpp>=1.2.0 mcp>=1.0 pytest>=8.0'
FULL_PKGS='resemblyzer>=0.1.4 silero-vad>=5.1 scikit-learn>=1.3'

sha() { if command -v shasum >/dev/null 2>&1; then shasum -a 256; else sha256sum; fi; }

# Skip the whole pip phase when nothing that matters has changed. This is what
# makes day-to-day restarts instant without splitting setup and start into two
# separate scripts a newcomer could run in the wrong order.
STAMP_FILE='venv/.trove-stamp'
STAMP=$(printf 'v1|%s|%s|%s|%s|%s' \
          "$FULL" "$YTDLP_SPEC" "$CORE_PKGS" "$FULL_PKGS" \
          "$("$VPY" -c 'import sys; print(sys.version)' 2>/dev/null || echo none)" \
        | sha | awk '{print $1}')

if [ -f "$STAMP_FILE" ] && [ "$(cat "$STAMP_FILE" 2>/dev/null)" = "$STAMP" ]; then
  ok "dependencies already installed"
else
  info "installing dependencies (first run takes a few minutes) ..."
  "$VPY" -m pip install -q -U pip wheel
  # shellcheck disable=SC2086
  "$VPY" -m pip install -q -U $CORE_PKGS
  if [ "$FULL" -eq 1 ]; then
    info "installing diarization — this pulls PyTorch, roughly 1.3GB ..."
    # shellcheck disable=SC2086
    "$VPY" -m pip install -q -U $FULL_PKGS
  fi
  printf '%s' "$STAMP" > "$STAMP_FILE"
  ok "dependencies installed"
fi

# yt-dlp moves fast — extractors break weekly — but nightly builds carry real
# version numbers, so `-U` is a cheap no-op once current. Check at most daily,
# and never let a network failure stop the app from starting.
YTDLP_MARK='venv/.trove-ytdlp-checked'
ytdlp_check_due() {
  [ -f "$YTDLP_MARK" ] || return 0
  [ -n "$(find "$YTDLP_MARK" -mmin +1440 2>/dev/null)" ]
}

if ytdlp_check_due; then
  info "updating yt-dlp ..."
  if "$VPY" -m pip install -q -U --pre "$YTDLP_SPEC"; then
    : > "$YTDLP_MARK"
    ok "yt-dlp $("$VPY" -m yt_dlp --version 2>/dev/null || echo '?')"
  else
    warn "could not update yt-dlp (offline?) — using the installed version"
  fi
else
  ok "yt-dlp $("$VPY" -m yt_dlp --version 2>/dev/null || echo '?')  ${D}(checked recently)${X}"
fi

# yt-dlp finds its JS runtime on PATH; runner.py puts venv/bin there for the
# subprocess. Surface the state here so a degraded YouTube setup is visible at
# startup rather than as a confusing extraction failure later.
if [ -x venv/bin/deno ]; then
  ok "JS runtime: deno $(venv/bin/deno --version 2>/dev/null | head -1 | awk '{print $2}')"
else
  warn "no Deno in the venv — YouTube extraction will be degraded"
fi

# --------------------------------------------------------------- tailwind ---
if [ ! -x tools/tailwindcss ]; then
  info "downloading the Tailwind CSS standalone CLI ..."
  mkdir -p tools
  OS=$(uname -s | tr '[:upper:]' '[:lower:]')
  ARCH=$(uname -m)
  case "$OS-$ARCH" in
    darwin-arm64)  URL=https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-macos-arm64 ;;
    darwin-x86_64) URL=https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-macos-x64 ;;
    linux-x86_64)  URL=https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-x64 ;;
    linux-aarch64) URL=https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-arm64 ;;
    *) die "unsupported platform: $OS-$ARCH" ;;
  esac
  curl -sSL "$URL" -o tools/tailwindcss
  chmod +x tools/tailwindcss
fi

# Only rebuild when an input actually changed.
css_stale() {
  [ ! -f static/app.css ] || \
  [ -n "$(find tailwind.config.js styles templates -newer static/app.css 2>/dev/null | head -1)" ]
}
if css_stale; then
  info "building CSS ..."
  # stdout only — Tailwind reports real errors on stderr, and silencing those
  # turns a broken stylesheet into a silently unstyled app.
  ./tools/tailwindcss -c tailwind.config.js -i styles/input.css -o static/app.css --minify >/dev/null
  # Tailwind skips the write when output is byte-identical, which leaves the
  # mtime behind the inputs and makes the check above fire again next launch.
  # A fresh checkout has every file stamped within the same second, so that is
  # the normal case, not an edge one. Touch it so the check can settle.
  touch static/app.css
  ok "CSS built"
else
  ok "CSS up to date"
fi

# ------------------------------------------------------------------ serve ---
PORT="${PORT:-8899}"
HOST="${HOST:-127.0.0.1}"
export PORT HOST

# 0.0.0.0 is a bind address, not something a browser should be pointed at.
BROWSER_HOST="$HOST"
[ "$BROWSER_HOST" = '0.0.0.0' ] && BROWSER_HOST='127.0.0.1'
URL="http://$BROWSER_HOST:$PORT"

if [ "$OPEN_BROWSER" -eq 1 ] && command -v open >/dev/null 2>&1; then
  # Wait for the port to actually accept a connection before opening the
  # browser. A fixed sleep either races the server or wastes time.
  (
    i=0
    while [ "$i" -lt 60 ]; do
      if "$VPY" - "$BROWSER_HOST" "$PORT" <<'PY' >/dev/null 2>&1
import socket, sys
s = socket.socket()
s.settimeout(0.5)
sys.exit(0 if s.connect_ex((sys.argv[1], int(sys.argv[2]))) == 0 else 1)
PY
      then
        open "$URL"
        exit 0
      fi
      i=$((i + 1))
      sleep 0.5
    done
  ) &
fi

printf '\n  %sTrove is running at %s%s\n' "$B" "$URL" "$X"
printf '  %spress ctrl-c to stop%s\n\n' "$D" "$X"

exec "$VPY" app.py
