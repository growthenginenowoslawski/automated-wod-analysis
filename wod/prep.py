"""Video prep: probe, auto-orient (using the pose model), downscale, extract audio."""
import json
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROTATIONS = {  # name -> (ffmpeg filter, cv2 rotate code)
    "none": ("", None),
    "cw": ("transpose=1", cv2.ROTATE_90_CLOCKWISE),
    "ccw": ("transpose=2", cv2.ROTATE_90_COUNTERCLOCKWISE),
    "180": ("hflip,vflip", cv2.ROTATE_180),
}


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])}... failed: {r.stderr[-500:]}")
    return r.stdout


def probe(path):
    out = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    info = json.loads(out)
    dur = float(info["format"]["duration"])
    has_audio = any(s.get("codec_type") == "audio" for s in info["streams"])
    return {"duration": dur, "has_audio": has_audio}


def sample_frames(path, n=8, height=480):
    """Grab n evenly spaced frames (already display-rotated by ffmpeg metadata)."""
    dur = probe(path)["duration"]
    frames = []
    with tempfile.TemporaryDirectory() as td:
        for i in range(n):
            t = dur * (i + 1) / (n + 1)
            f = Path(td) / f"f{i}.jpg"
            run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(path),
                 "-vf", f"scale=-2:{height}", "-frames:v", "1", str(f)])
            img = cv2.imread(str(f))
            if img is not None:
                frames.append(img)
    return frames


def detect_rotation(path, landmarker_factory):
    """Try each rotation on sample frames; pick the one where a person is found upright
    (shoulders above hips, head above shoulders) most often."""
    import mediapipe as mp
    frames = sample_frames(path)
    best, best_score, scores = "none", -1, {}
    for name, (_, code) in ROTATIONS.items():
        lm = landmarker_factory(video=False)
        score = 0.0
        for img in frames:
            im = img if code is None else cv2.rotate(img, code)
            r = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(im, cv2.COLOR_BGR2RGB)))
            if not r.pose_landmarks:
                continue
            p = r.pose_landmarks[0]
            sh = (p[11].y + p[12].y) / 2
            hp = (p[23].y + p[24].y) / 2
            if p[0].y < sh < hp:  # nose above shoulders above hips (y grows down)
                score += np.mean([p[i].visibility for i in (0, 11, 12, 23, 24)])
        lm.close()
        scores[name] = round(score, 2)
        if score > best_score:
            best, best_score = name, score
    return best, scores


def transcode(src, dst, rotation="none", long_side=640, fps=15):
    # MediaPipe works at ~256px internally, so 640px on the long side loses nothing and is fast.
    scale = f"scale='if(gt(iw,ih),{long_side},-2)':'if(gt(iw,ih),-2,{long_side})'"
    vf = [f for f in [ROTATIONS[rotation][0], scale, f"fps={fps}"] if f]
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", ",".join(vf), "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", str(dst)])


def extract_audio(src, dst, sr=16000):
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", str(sr), str(dst)])
