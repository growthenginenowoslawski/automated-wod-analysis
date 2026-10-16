#!/usr/bin/env bash
# Automated WOD Analysis: one-time setup on a Mac.
#   bash install/mac.sh
#   WOD_INBOX="$HOME/Library/Mobile Documents/com~apple~CloudDocs/WODs" bash install/mac.sh   # watch an iCloud folder
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
WOD_HOME="${WOD_HOME:-$HOME/WODs}"
WOD_INBOX="${WOD_INBOX:-$WOD_HOME/inbox}"
VENV="$HOME/.wod-venv"
say() { printf "\n\033[1m%s\033[0m\n" "$*"; }

say "1/4 Tools (Homebrew, ffmpeg, Python 3.10-3.12)"
if ! command -v brew >/dev/null; then
  echo "Install Homebrew first: https://brew.sh (one line in Terminal), then run this again."; exit 1
fi
command -v ffmpeg >/dev/null || brew install ffmpeg
PY=""
for v in 3.12 3.11 3.10; do command -v "python$v" >/dev/null && PY="python$v" && break; done
if [ -z "$PY" ]; then brew install python@3.12; PY=python3.12; fi

say "2/4 Installing the analyzer into $VENV"
"$PY" -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -e "$HERE"
mkdir -p "$HOME/.local/bin"
ln -sf "$VENV/bin/wod" "$HOME/.local/bin/wod"
grep -q '.local/bin' "$HOME/.zshrc" 2>/dev/null || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.zshrc"
export PATH="$HOME/.local/bin:$PATH"

say "3/4 Body-tracking model and data folder ($WOD_HOME)"
WOD_HOME="$WOD_HOME" wod doctor --download

say "4/4 Inbox watcher (drop a video + its workout into $WOD_INBOX)"
mkdir -p "$WOD_INBOX" "$HOME/Library/LaunchAgents"
PLIST="$HOME/Library/LaunchAgents/com.automated-wod-analysis.inbox.plist"
sed -e "s#__WOD#$VENV/bin/wod#g" -e "s#__INBOX__#$WOD_INBOX#g" -e "s#__WOD_HOME__#$WOD_HOME#g" \
  "$HERE/install/com.wod.inbox.plist.template" > "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

say "Done. Open a new Terminal window, then:"
echo "  wod analyze ~/Downloads/IMG_1234.MOV --workout examples/amrap.txt"
echo "  wod stats · wod dashboard · wod summary"
echo "  Using Claude Code: cp -R \"$HERE/skills/automated-wod-analysis\" ~/.claude/skills/"
