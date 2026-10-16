"""Inbox watcher (Mac, Windows, Linux): drop a video plus its workout into the inbox and it gets analyzed.

For each video in the inbox it needs the workout, from (first match wins):
  VIDEO.txt · VIDEO.json · workout.txt (applies to every video in the inbox)
  VIDEO.png/.jpg/.jpeg/.heic or workout.png/... (a screenshot) - turned into text by the Claude Code CLI
  (`claude`) or the Codex CLI (`codex`) if one is installed, using your own plan, text only.
"""
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import db as DB

VIDEO_EXT = {".mov", ".mp4", ".m4v", ".avi", ".mkv"}
IMG_EXT = [".png", ".jpg", ".jpeg", ".heic", ".webp"]
PROMPT = ("Read the image at {img}. It shows a CrossFit workout. Output ONLY the workout as plain lines, for example:\n"
          "AMRAP 8:00\n36 Double Unders\n6 Toes to Bar\n6 Power Snatch 95/65lbs\nInclude rounds, rest and time caps. No other text.")


def notify(title, msg):
    print(f"[{title}] {msg}", flush=True)
    try:
        if platform.system() == "Darwin":
            subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "{title}"'], capture_output=True)
        elif platform.system() == "Windows":
            ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
                  "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                  f"$x=$t.GetElementsByTagName('text');$x.Item(0).AppendChild($t.CreateTextNode('{title}'))>$null;"
                  f"$x.Item(1).AppendChild($t.CreateTextNode('{msg}'))>$null;"
                  "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('WOD').Show([Windows.UI.Notifications.ToastNotification]::new($t))")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
    except Exception:
        pass


def screenshot_to_text(img, out_txt):
    prompt = PROMPT.format(img=img)
    for cmd in (["claude", "-p", "--model", "haiku", prompt], ["codex", "exec", prompt]):
        if shutil.which(cmd[0]):
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if r.returncode == 0 and r.stdout.strip():
                Path(out_txt).write_text(r.stdout.strip() + "\n")
                return True
    return False


def _stable(p, wait=3):
    s1 = p.stat().st_size
    time.sleep(wait)
    return s1 == p.stat().st_size and s1 > 0


def process_inbox(inbox):
    done_dir = DB.WOD_HOME / "done"
    for v in sorted(inbox.iterdir()):
        if v.suffix.lower() not in VIDEO_EXT or not _stable(v):
            continue
        base = v.with_suffix("")
        wtxt = next((p for p in [base.with_suffix(".txt"), base.with_suffix(".json"), inbox / "workout.txt"] if p.exists()), None)
        if wtxt is None:
            img = next((p for e in IMG_EXT for p in [base.with_suffix(e), inbox / f"workout{e}"] if p.exists()), None)
            if img and screenshot_to_text(img, base.with_suffix(".txt")):
                wtxt = base.with_suffix(".txt")
        if wtxt is None:
            notify("WOD analyzer", f"{v.name}: add {base.name}.txt with the workout (or a screenshot) to analyze it")
            continue
        out = done_dir / base.name
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "report.txt", "w") as log:
            r = subprocess.run([sys.executable, "-m", "wod.cli", "analyze", str(v), "--workout", str(wtxt)],
                               stdout=log, stderr=subprocess.STDOUT, cwd=str(Path(__file__).resolve().parent.parent))
        if r.returncode == 0:
            for f in [v, wtxt] + [base.with_suffix(e) for e in IMG_EXT]:
                if f.exists():
                    shutil.move(str(f), str(out / f.name))
            subprocess.run([sys.executable, "-m", "wod.cli", "dashboard", "--no-open"], capture_output=True,
                           cwd=str(Path(__file__).resolve().parent.parent))
            score = next((l.replace("*", "") for l in (out / "report.txt").read_text().splitlines() if "Score" in l), "done")
            notify(f"WOD analyzed: {base.name}", score.strip())
        else:
            notify("WOD analyzer", f"{v.name} failed, see {out / 'report.txt'}")


def watch(inbox, once=False, every=20):
    inbox.mkdir(parents=True, exist_ok=True)
    print(f"Watching {inbox} (Ctrl+C to stop)…", flush=True)
    while True:
        process_inbox(inbox)
        if once:
            return
        time.sleep(every)
