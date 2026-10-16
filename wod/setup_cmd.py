"""`wod setup`: everything a non-technical user needs, in one command (Mac, Windows, Linux).

1. data folders in ~/WODs   2. body-tracking model   3. ffmpeg check (bundled, nothing to install)
4. instructions for AI assistants: a Claude skill in ~/.claude/skills and a note in ~/.codex/AGENTS.md
5. inbox watcher that starts automatically (launchd on Mac, Task Scheduler on Windows)
"""
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from . import db as DB

GUIDE = Path(__file__).with_name("agent_guide.md")
SKILL_FRONT = ("---\nname: automated-wod-analysis\ndescription: Analyze CrossFit/WOD workout videos into reps, splits, "
               "transitions, rest and fresh-speed benchmarks stored in a local database, and answer questions about past "
               "workouts. Use when someone sends a workout video or a workout screenshot, or asks about their training data.\n---\n\n")
CODEX_START, CODEX_END = "<!-- automated-wod-analysis:start -->", "<!-- automated-wod-analysis:end -->"
CODEX_NOTE = (f"{CODEX_START}\n## Workout videos (Automated WOD Analysis)\n"
              "When the user wants a CrossFit/workout video analyzed or asks about their training data, run `wod guide` "
              "and follow those instructions. Do every step for the user.\n{CODEX_END}\n")


def guide_text():
    return GUIDE.read_text(encoding="utf-8")


def skill_text():
    return SKILL_FRONT + guide_text()


def _wod_exe():
    exe = shutil.which("wod")
    if exe:
        return exe
    cand = Path(sys.executable).with_name("wod.exe" if platform.system() == "Windows" else "wod")
    return str(cand) if cand.exists() else None


def install_assistant_files():
    done = []
    sk = Path.home() / ".claude" / "skills" / "automated-wod-analysis" / "SKILL.md"
    sk.parent.mkdir(parents=True, exist_ok=True)
    sk.write_text(skill_text(), encoding="utf-8")
    done.append(f"Claude skill → {sk}")
    cx = Path.home() / ".codex" / "AGENTS.md"
    cx.parent.mkdir(parents=True, exist_ok=True)
    old = cx.read_text(encoding="utf-8") if cx.exists() else ""
    if CODEX_START in old:
        pre, rest = old.split(CODEX_START, 1)
        post = rest.split(CODEX_END, 1)[1] if CODEX_END in rest else ""
        new = pre + CODEX_NOTE.rstrip("\n") + post
    else:
        new = (old.rstrip("\n") + "\n\n" if old.strip() else "") + CODEX_NOTE
    cx.write_text(new, encoding="utf-8")
    done.append(f"Codex note → {cx}")
    return done


def install_watcher(inbox):
    exe = _wod_exe()
    if not exe:
        return "inbox watcher skipped (couldn't find the wod program)"
    system = platform.system()
    log = DB.WOD_HOME / "watcher.log"
    if system == "Darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / "com.automated-wod-analysis.inbox.plist"
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.automated-wod-analysis.inbox</string>
  <key>ProgramArguments</key><array><string>{exe}</string><string>watch</string><string>--once</string>
    <string>--inbox</string><string>{inbox}</string></array>
  <key>EnvironmentVariables</key><dict><key>WOD_HOME</key><string>{DB.WOD_HOME}</string></dict>
  <key>WatchPaths</key><array><string>{inbox}</string></array>
  <key>StandardOutPath</key><string>{log}</string><key>StandardErrorPath</key><string>{log}</string>
</dict></plist>
""")
        subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
        r = subprocess.run(["launchctl", "load", str(plist)], capture_output=True, text=True)
        return "inbox watcher on (starts automatically)" if r.returncode == 0 else f"inbox watcher not started: {r.stderr.strip()}"
    if system == "Windows":
        r = subprocess.run(["schtasks", "/Create", "/F", "/SC", "ONLOGON", "/TN", "AutomatedWODAnalysis",
                            "/TR", f'"{exe}" watch --inbox "{inbox}"'], capture_output=True, text=True)
        if r.returncode == 0:
            subprocess.run(["schtasks", "/Run", "/TN", "AutomatedWODAnalysis"], capture_output=True)
            return "inbox watcher on (starts when you log in)"
        return f"inbox watcher not started: {r.stderr.strip() or r.stdout.strip()}"
    return f"inbox watcher: run `wod watch` to process {inbox} (no autostart on this system)"


def setup(no_watcher=False):
    from .cli import find_model
    print("Setting up Automated WOD Analysis…\n")
    home = DB.WOD_HOME
    inbox = home / "inbox"
    for d in (home, inbox, home / "archive", home / "done"):
        d.mkdir(parents=True, exist_ok=True)
    DB.connect().close()
    print(f"✓ data folder: {home}")
    from . import ff
    print(f"✓ video tools: {'system ffmpeg' if shutil.which('ffmpeg') else 'bundled ffmpeg'} ({ff.exe()})")
    print(f"✓ body-tracking model: {find_model(download=True)}")
    for line in install_assistant_files():
        print(f"✓ {line}")
    if not no_watcher:
        print(f"✓ {install_watcher(inbox)}")
    print(f"""
Ready. Three ways to use it:
  1. Ask your AI assistant (Claude Code, Codex/ChatGPT): "Analyze the workout video in my Downloads" and send the workout.
  2. Drop a video plus a .txt of the workout with the same name into {inbox}
  3. In a terminal:  wod analyze VIDEO --workout "AMRAP 8:00\\n36 Double Unders\\n6 Toes to Bar"
Then: wod stats · wod dashboard · wod summary""")
