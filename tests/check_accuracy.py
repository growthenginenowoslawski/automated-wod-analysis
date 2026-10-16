"""Re-run the counting on saved data for every labeled workout and compare with the truth.

  python -m tests.check_accuracy            # uses $WOD_HOME/archive (default ~/WODs/archive)

Truth comes from two places:
  - tests/ground_truth.json (hand-labeled videos shipped with the analyzer)
  - every correction you've saved with `wod correct` (your own videos)
Run it after any change to the counting rules; everything must PASS.
"""
import json
import sys
import tempfile
from pathlib import Path

from wod import db as DB
from wod.analyze import analyze
from wod.features import Audio, Signals
from wod.spec import parse_text


def run(d, spec):
    with tempfile.TemporaryDirectory() as td:
        wav = DB.audio_wav(d, td)
        return analyze(Signals(DB.load_pose(d)), spec, Audio(wav) if wav else None)


ok_all, checked = True, 0
arch = DB.WOD_HOME / "archive"
truth = json.load(open(Path(__file__).parent / "ground_truth.json"))
for name, gt in truth.items():
    d = next(iter(sorted(arch.glob(f"*{name}*"))), None)
    if d is None or not any((d / f).exists() for f in ("pose.json.gz", "pose.json")):
        print(f"skip {name}: not in {arch}")
        continue
    res = run(d, parse_text(gt["workout"]))
    got = {}
    for r in res["rounds"]:
        for b in r["blocks"]:
            got.setdefault(b["movement"], []).append(b["reps"])
    checks = [("rounds_complete", res["totals"]["rounds_complete"], gt["expected"]["rounds_complete"]),
              ("rounds_found", len(res["rounds"]), gt["expected"].get("rounds_found", gt["expected"]["rounds_complete"]))]
    checks += [(mv, got.get(mv, []), reps) for mv, reps in gt["expected"]["reps"].items()]
    checks += [(f"{mv} steps found", len(got.get(mv, [])), k) for mv, k in gt["expected"].get("steps_found", {}).items()]
    for label, g, e in checks:
        ok = g == e
        ok_all &= ok
        checked += 1
        print(f"{'PASS' if ok else 'FAIL'} {name} {label}: got {g} expected {e}")

con = DB.connect()
for c in con.execute("SELECT c.*, w.archive_dir, w.spec_json FROM corrections c JOIN workouts w ON w.id = c.workout_id WHERE c.field = 'reps'"):
    res = run(Path(c["archive_dir"]), json.loads(c["spec_json"]))
    got = [b["reps"] for r in res["rounds"] for b in r["blocks"]
           if (c["round"] is None or r["round"] == c["round"]) and c["movement_key"] in (b["key"], b["movement"])]
    ok = got == [int(c["value"])] * len(got) and got
    ok_all &= bool(ok)
    checked += 1
    print(f"{'PASS' if ok else 'FAIL'} {c['workout_id']} round {c['round']} {c['movement_key']}: tracker {got}, you said {c['value']}")
print(f"\n{checked} checks")
sys.exit(0 if ok_all else 1)
