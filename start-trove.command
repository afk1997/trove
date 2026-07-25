#!/usr/bin/env bash
#
# Double-click this file in Finder to start Trove.
#
# Finder launches .command files with the working directory set to your home
# folder, not the folder the file lives in — so the one thing this wrapper has
# to do is find its way back to the repo before handing off to trove.sh.
#
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -x ./trove.sh ]; then
  echo "trove.sh is missing or not executable in $(pwd)" >&2
  echo "try:  chmod +x trove.sh start-trove.command" >&2
  read -r -p "press return to close " _ 2>/dev/null || true
  exit 1
fi

# Keep the Terminal window readable if the bootstrap fails, instead of letting
# it vanish with the error still on screen.
trap 'echo; read -r -p "Trove exited. Press return to close this window. " _ 2>/dev/null || true' EXIT

./trove.sh "$@"
