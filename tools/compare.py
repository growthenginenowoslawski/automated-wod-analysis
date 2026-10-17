"""Compare browser tracking with the Python tool's tracking, then run the counting engine on both.

  python compare.py <name: IMG_2787|IMG_2803> <browser pose.json>
"""
import gzip
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

S = Path(__file__).resolve().parent.parent
REF = {"IMG_2787": S / "home3/archive/2026-10-15_IMG_2787", "IMG_2803": S / "home3/archive/2026-10-16_IMG_2803"}
name, bpath = sys.argv[1], sys.argv[2]
ref_dir = REF[name]
ref = json.load(gzip.open(ref_dir / "pose.json.gz"))
br = json.load(open(bpath))

# ---- landmark agreement ----
R, B = ref["frames"], br["frames"]
n = min(len(R), len(B))
both = only_ref = only_br = 0
d_all, d_key = [], []
KEY = [0, 11, 12, 15, 16, 23, 24, 25, 26, 27, 28]
for i in range(n):
    a, b = R[i]["p"], B[i]["p"]
    if a and b:
        both += 1
        A, Bb = np.array(a)[:, :2], np.array(b)[:, :2]
        d = np.linalg.norm(A - Bb, axis=1)
        d_all.append(d.mean())
        d_key.append(d[KEY].mean())
    elif a:
        only_ref += 1
    elif b:
        only_br += 1
d_key = np.array(d_key)
print(f"frames: python {len(R)}, browser {len(B)}")
print(f"body found: python {sum(1 for f in R if f['p'])/len(R)*100:.1f}%, browser {sum(1 for f in B if f['p'])/len(B)*100:.1f}%")
print(f"both {both}, only python {only_ref}, only browser {only_br}")
print(f"key-joint distance (fraction of frame): median {np.median(d_key):.4f}, 90th pct {np.percentile(d_key, 90):.4f}, "
      f"share of frames within 1% of frame: {(d_key < 0.01).mean()*100:.1f}%, within 3%: {(d_key < 0.03).mean()*100:.1f}%")

# ---- counting engine on the browser data ----
sys.path.insert(0, "/home/claude/wod-analyzer")
home = Path(tempfile.mkdtemp())
os.environ["WOD_HOME"] = str(home)
arch = home / "archive" / ref_dir.name
arch.mkdir(parents=True)
for f in ("audio.m4a", "workout.json", "source.json"):
    if (ref_dir / f).exists():
        shutil.copy(ref_dir / f, arch / f)
with gzip.open(arch / "pose.json.gz", "wt") as fh:
    json.dump(br, fh)

from wod import db as DB  # noqa: E402
from wod.analyze import analyze  # noqa: E402
from wod.features import Audio, Signals  # noqa: E402
from wod.spec import parse_text  # noqa: E402

truth = json.load(open("/home/claude/wod-analyzer/tests/ground_truth.json"))[name]
spec = parse_text(truth["workout"])


def run(d):
    with tempfile.TemporaryDirectory() as td:
        wav = DB.audio_wav(d, td)
        return analyze(Signals(DB.load_pose(d)), spec, Audio(wav) if wav else None)


def summarize(res):
    got = {}
    for r in res["rounds"]:
        for b in r["blocks"]:
            got.setdefault(b["movement"], []).append(b["reps"])
    return res["totals"]["rounds_complete"], len(res["rounds"]), got


ok_all = True
for label, d in (("python", ref_dir), ("browser", arch)):
    res = run(d)
    rc, rf, got = summarize(res)
    exp = truth["expected"]
    checks = [("rounds_complete", rc, exp["rounds_complete"]),
              ("rounds_found", rf, exp.get("rounds_found", exp["rounds_complete"]))]
    checks += [(mv, got.get(mv, []), reps) for mv, reps in exp["reps"].items()]
    checks += [(f"{mv} steps found", len(got.get(mv, [])), k) for mv, k in exp.get("steps_found", {}).items()]
    print(f"\n== engine on {label} tracking")
    for lab, g, e in checks:
        ok = g == e
        if label == "browser":
            ok_all &= ok
        print(f"  {'PASS' if ok else 'FAIL'} {lab}: got {g} expected {e}")
    tot = res["totals"]
    print("  totals:", {k: tot.get(k) for k in ("rounds_complete", "elapsed_s", "moving_s", "between_s")})
    json.dump(res, open(Path(bpath).with_suffix(f".{label}.result.json"), "w"), default=str)
print("\nALL BROWSER CHECKS PASS" if ok_all else "\nSOME BROWSER CHECKS FAIL")
