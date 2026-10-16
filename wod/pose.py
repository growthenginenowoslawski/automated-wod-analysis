"""Pose extraction with MediaPipe Pose Landmarker (runs locally, free)."""
import json

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mpp
from mediapipe.tasks.python import vision


import numpy as np

MAX_PEOPLE = int(__import__("os").environ.get("WOD_PEOPLE", "1"))   # 2 = also track a training partner (experimental)


def make_factory(model_path, num_poses=1):
    def factory(video=True):
        opts = vision.PoseLandmarkerOptions(
            base_options=mpp.BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO if video else vision.RunningMode.IMAGE,
            num_poses=num_poses if video else 1, min_pose_detection_confidence=0.4, min_tracking_confidence=0.4)
        return vision.PoseLandmarker.create_from_options(opts)
    return factory


def extract(video_path, factory, out_json=None, progress=None):
    lm = factory(video=True)
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    W, H = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1, cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1
    n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    rows, i = [], 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        ts = int(i * 1000 / fps)
        r = lm.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,
                                         data=cv2.cvtColor(f, cv2.COLOR_BGR2RGB)), ts)
        people = []
        for lmk in (r.pose_landmarks or []):
            pts = [[round(p.x, 4), round(p.y, 4), round(p.visibility, 3)] for p in lmk]
            people.append({"lm": pts, "color": _torso_color(f, pts)})
        row = {"t": round(ts / 1000, 3), "p": people[0]["lm"] if people else None}
        if len(people) > 1 or people and people[0]["color"] is not None:
            row["people"] = people
        rows.append(row)
        i += 1
        if progress and n_total and i % 300 == 0:
            progress(i / n_total)
    cap.release()
    lm.close()
    data = {"fps": fps, "aspect": round(W / H, 4), "frames": rows}
    if out_json:
        json.dump(data, open(out_json, "w"))
    return data


def _torso_color(frame, pts):
    """Median colour of the chest/stomach area (between shoulders and hips): a cheap identity signature."""
    h, w = frame.shape[:2]
    xs = [pts[i][0] for i in (11, 12, 23, 24)]
    ys = [pts[i][1] for i in (11, 12, 23, 24)]
    x0, x1 = int(max(0, min(xs)) * w), int(min(1, max(xs)) * w)
    y0, y1 = int(max(0, min(ys)) * h), int(min(1, max(ys)) * h)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    pad_x, pad_y = (x1 - x0) // 4, (y1 - y0) // 5
    patch = frame[y0 + pad_y:y1 - pad_y, x0 + pad_x:x1 - pad_x]
    if patch.size == 0:
        return None
    lab = cv2.cvtColor(patch, cv2.COLOR_BGR2LAB).reshape(-1, 3)
    return [int(v) for v in np.median(lab, 0)]


def _hip(lm):
    return ((lm[23][0] + lm[24][0]) / 2, (lm[23][1] + lm[24][1]) / 2)


def select_main_athlete(data):
    """When two people are tracked, follow the main athlete.

    Frames with one person keep that person. In frames with two, keep the one closest to where the athlete
    was a moment ago (people don't teleport); if there's no recent position, use torso colour against the
    colour of the person seen alone most often."""
    frames = data["frames"]
    multi = sum(1 for r in frames if len(r.get("people", [])) > 1)
    data["multi_person_frames"] = multi
    if not multi:
        return data
    solo = np.array([r["people"][0]["color"] for r in frames if len(r.get("people", [])) == 1 and r["people"][0].get("color")], float)
    ref = np.median(solo, 0) if len(solo) else None
    last, last_t = None, -99.0
    for r in frames:
        people = r.get("people", [])
        if len(people) == 1:
            r["p"] = people[0]["lm"]
        elif len(people) > 1:
            if last is not None and r["t"] - last_t < 1.5:
                pick = min(people, key=lambda pp: (_hip(pp["lm"])[0] - last[0]) ** 2 + (_hip(pp["lm"])[1] - last[1]) ** 2)
            elif ref is not None:
                pick = min(people, key=lambda pp: np.linalg.norm(np.array(pp["color"]) - ref) if pp.get("color") else 1e9)
            else:
                pick = people[0]
            r["p"] = pick["lm"]
        if r.get("p"):
            last, last_t = _hip(r["p"]), r["t"]
    return data


def _worker(args):
    model_path, seg_path, offset, out_path = args
    d = extract(seg_path, make_factory(model_path, MAX_PEOPLE))
    for r in d["frames"]:
        r["t"] = round(r["t"] + offset, 3)
    json.dump(d, open(out_path, "w"))
    return out_path


def extract_parallel(video_path, model_path, out_json, workers=None, progress=None):
    """Split the video into segments and track them on several CPU cores at once."""
    import os
    import subprocess
    import tempfile
    from concurrent.futures import ProcessPoolExecutor, as_completed
    workers = workers or max(1, min(8, (os.cpu_count() or 2)))
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(video_path)], capture_output=True, text=True).stdout.strip())
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    W, H = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1, cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1
    cap.release()
    if workers == 1 or dur < 120:
        data = select_main_athlete(extract(video_path, make_factory(model_path, MAX_PEOPLE), None, progress))
        if out_json:
            json.dump(data, open(out_json, "w"))
        return data
    n = workers * 2                                   # more pieces than cores keeps every core busy
    step = dur / n
    with tempfile.TemporaryDirectory() as td:
        jobs = []
        for i in range(n):
            seg = os.path.join(td, f"seg{i}.mp4")
            # re-encode so each piece starts on its own keyframe at exactly i*step
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{i * step:.3f}", "-t", f"{step:.3f}", "-i", str(video_path),
                            "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", seg], check=True)
            jobs.append((str(model_path), seg, i * step, os.path.join(td, f"seg{i}.json")))
        done = 0
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_worker, j) for j in jobs]
            for _ in as_completed(futs):
                done += 1
                if progress:
                    progress(done / n)
        frames = []
        for j in jobs:
            frames += json.load(open(j[3]))["frames"]
    frames.sort(key=lambda r: r["t"])
    data = select_main_athlete({"fps": fps, "aspect": round(W / H, 4), "frames": frames})
    if out_json:
        json.dump(data, open(out_json, "w"))
    return data
