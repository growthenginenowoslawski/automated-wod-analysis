#!/usr/bin/env bash
# Automated WOD Analysis: setup for Mac (and Linux). No password, no admin rights, no Homebrew.
#   curl -LsSf https://raw.githubusercontent.com/growthenginenowoslawski/automated-wod-analysis/main/install/mac.sh | bash
set -euo pipefail
SRC="${WOD_SOURCE:-https://github.com/growthenginenowoslawski/automated-wod-analysis/archive/refs/heads/main.zip}"
UV="$HOME/.local/bin/uv"

echo "1/3 Installing uv (a small tool that brings its own Python)…"
if ! command -v uv >/dev/null && [ ! -x "$UV" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
command -v uv >/dev/null && UV="$(command -v uv)"

echo "2/3 Installing Automated WOD Analysis…"
"$UV" tool install --force --python 3.12 "automated-wod-analysis @ $SRC"

"$UV" tool update-shell >/dev/null 2>&1 || true     # so new terminal windows find `wod`

echo "3/3 Setting up (model, folders, assistant instructions, inbox watcher)…"
"$HOME/.local/bin/wod" setup

echo
echo "Done. Open a new terminal window and type: wod doctor"
