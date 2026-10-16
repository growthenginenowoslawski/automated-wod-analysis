"""ffmpeg without asking the user to install anything.

Uses a system ffmpeg if there is one, otherwise the copy bundled with the `imageio-ffmpeg` package.
Probing (duration, audio, recording time) parses `ffmpeg -i` output, so ffprobe isn't needed either.
"""
import re
import shutil
import subprocess
from datetime import datetime
from functools import lru_cache


@lru_cache(maxsize=1)
def exe():
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise SystemExit("ffmpeg not found. Run `wod setup` (it installs everything), or install ffmpeg.")


def run(args, check=True):
    """Run ffmpeg with the given arguments (without the leading 'ffmpeg')."""
    r = subprocess.run([exe(), "-hide_banner", "-loglevel", "error", "-y"] + [str(a) for a in args],
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-500:]}")
    return r


def probe(path):
    """{'duration': seconds, 'has_audio': bool, 'creation_time': datetime|None, 'width', 'height', 'fps'}"""
    r = subprocess.run([exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    err = r.stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
    ct = None
    m = re.search(r"creation_time\s*:\s*(\S+)", err)
    if m:
        try:
            ct = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
        except ValueError:
            ct = None
    v = re.search(r"Stream #.*Video:.*?(\d{2,5})x(\d{2,5})", err)
    f = re.search(r"(\d+(?:\.\d+)?) fps", err)
    return {"duration": dur, "has_audio": bool(re.search(r"Stream #.*Audio:", err)), "creation_time": ct,
            "width": int(v.group(1)) if v else None, "height": int(v.group(2)) if v else None,
            "fps": float(f.group(1)) if f else None}
