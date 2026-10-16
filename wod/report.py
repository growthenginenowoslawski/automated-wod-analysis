"""Reports: markdown table, JSON, CSV log rows, review frames for flagged windows."""
import csv
import json
import subprocess
from datetime import date
from pathlib import Path
from . import ff as _ff


def mmss(s):
    if s is None:
        return "-"
    m, sec = divmod(int(round(max(0, float(s)))), 60)
    return f"{m}:{sec:02d}"


def secs(s):
    return "-" if s is None else f"{float(s):.0f}s"


def _seq_markdown(res):
    sp, T = res["spec"], res["totals"]
    L = [f"## {sp.get('name') or 'Workout'}: {len(res['rounds'])} of {sp.get('rounds') or '?'} rounds on video"
         + (f", {mmss(sp['rest_s'])} rest" if sp.get("rest_s") else ""), ""]
    L.append(f"**{T['score']}** · moving {mmss(T['moving'])} · between steps {mmss(T['between'])} ({T['between_pct']:.0f}% of working time)"
             + (f" · rest {mmss(T['rest'])}" if T.get("rest") else ""))
    L.append("")
    R = res["rounds"]
    hdr = ["Step"] + [f"Round {r['round']}" for r in R]
    L.append("| " + " | ".join(hdr) + " |")
    L.append("|" + "---|" * len(hdr))
    labels = {}
    for r in R:
        for b in r["blocks"]:
            labels[b["position"]] = b["label"]
    for m in sp["movements"]:
        pass
    npos = max([b["position"] for r in R for b in r["blocks"]] or [0])
    for pos in range(1, npos + 1):
        row = [labels.get(pos, f"step {pos}")]
        for r in R:
            b = next((x for x in r["blocks"] if x["position"] == pos), None)
            if not b:
                row.append("not found")
                continue
            cell = secs(b["duration"])
            if b.get("unit") == "cal" and b["duration"]:
                rate = b["reps"] / b["duration"] * 60
                cell += f" · {rate:.0f} {b['unit']}/min"
            elif b.get("counted"):
                cell += f" · {b['reps']}" + (f"/{b['expected']}" if b.get("expected") and b["reps"] != b["expected"] else "") + " reps"
                if len(b["sets"]) > 1:
                    cell += " (" + "+".join(map(str, b["sets"])) + ")"
            elif b.get("hidden"):
                cell += " · count not visible"
            if b.get("transition_after") is not None and b["transition_after"] > 5:
                cell += f" · then {secs(b['transition_after'])}"
            if b.get("flag"):
                cell += " ⚠️"
            row.append(cell)
        L.append("| " + " | ".join(row) + " |")
    L.append("| Round time | " + " | ".join(mmss(r["duration"]) for r in R) + " |")
    L.append("| Rest after | " + " | ".join(mmss(r.get("rest_after")) if r.get("rest_after") else "-" for r in R) + " |")
    L.append("")
    # per-movement roll-up
    agg = {}
    for r in R:
        for b in r["blocks"]:
            a = agg.setdefault(b["key"], {"name": b["movement"], "dur": 0.0, "amt": 0.0, "unit": b.get("unit", "reps"), "n": 0})
            a["dur"] += b["duration"]
            a["amt"] += b["reps"] or 0
            a["n"] += 1
    L.append("**Per movement**")
    for a in agg.values():
        rate = a["amt"] / a["dur"] * 60 if a["dur"] else 0
        tail = f", {rate:.1f} cal/min average" if a["unit"] == "cal" else ""
        L.append(f"- {a['name']}: {mmss(a['dur'])} total over {a['n']} efforts{tail}")
    trans = [(b["transition_after"], r["round"], b["label"]) for r in R for b in r["blocks"] if b.get("transition_after") is not None]
    if trans:
        worst = sorted(trans, reverse=True)[:3]
        L.append("\n**Longest transitions:** " + "; ".join(f"round {rn} after {lab}: {secs(t)}" for t, rn, lab in worst))
    hid = sum(1 for r in R for b in r["blocks"] if b.get("hidden"))
    notes = []
    if hid:
        notes.append(f"{hid} steps were mostly hidden from the camera (behind the rig or another person), so they are timed but their reps aren't counted")
    if res.get("multi_person_frames"):
        notes.append("another person was in frame at times; the analyzer followed the athlete seen most often")
    notes += [f["why"] for f in res["flags"] if "movement" not in f]
    misses = [f for f in res["flags"] if f.get("why") == "not found in the video"]
    for f in misses:
        notes.append(f"round {f['round']}: {f['movement']} not found")
    wrong = [f for f in res["flags"] if f.get("why") == "rep count differs from the workout"]
    for f in wrong:
        notes.append(f"round {f['round']} {f['movement']}: counted {f['detected']}, workout says {f['expected']}")
    if notes:
        L.append("\n**Needs a look**")
        L += [f"- {x}" for x in notes]
    return "\n".join(L)


def to_markdown(res, hr=None):
    if res.get("mode") == "sequence":
        return _seq_markdown(res)
    sp = res["spec"]
    t0 = res["totals"]["start"]
    lines = []
    title = sp.get("name") or "Workout"
    mv = ", ".join(f"{m.get('reps') or ''} {m['name']}".strip() for m in sp["movements"])
    fmt = {"amrap": f"AMRAP {mmss(sp.get('time_cap_s'))}", "rounds": f"{sp.get('rounds')} rounds for time",
           "for_time": "For time"}.get(sp.get("format"), "")
    lines.append(f"## {title}: {fmt} — {mv}\n")
    T = res["totals"]
    if T.get("score"):
        lines.append(f"**Score on video: {T['score']}**  ")
    lines.append(f"Moving {mmss(T['moving'])} · between movements {mmss(T['between'])} ({T['between_pct']:.0f}%) · "
                 f"first rep → last rep {mmss(T['elapsed'])}\n")
    if res.get("observed_order") and [m["name"] for m in sp["movements"]] != res["observed_order"]:
        lines.append(f"_Order performed: {' → '.join(res['observed_order'])}_\n")
    # table: one row per round, one column group per movement in observed order
    order = res.get("observed_order") or [m["name"] for m in sp["movements"]]
    hdr = ["Round"]
    for i, m in enumerate(order):
        hdr += [m, "→ transition"]
    hdr += ["Round time"]
    if hr:
        hdr += ["Avg HR"]
    lines.append("| " + " | ".join(hdr) + " |")
    lines.append("|" + "---|" * len(hdr))
    for r in res["rounds"]:
        row = [str(r["round"]) + ("" if r["complete"] else " (partial)")]
        byname = {b["movement"]: b for b in r["blocks"]}
        for m in order:
            b = byname.get(m)
            if not b:
                row += ["-", "-"]
                continue
            reps = f"{b['reps']}" + (f"/{b['expected']}" if b.get("expected") and b["reps"] != b["expected"] else "")
            sets = "unbroken" if len(b["sets"]) == 1 else "+".join(map(str, b["sets"])) + f" (breaks {', '.join(secs(x) for x in b['breaks'])})"
            flag = " ⚠️" if b.get("flag") else ""
            row += [f"{secs(b['duration'])} · {reps} reps · {sets}{flag}", secs(b["transition_after"])]
        row.append(mmss(r["duration"]))
        if hr:
            row.append(str(hr.get(r["round"], "-")))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("**Per movement**")
    for m, pm in res["per_movement"].items():
        spr = pm["sec_per_rep"]
        lines.append(f"- {m}: {pm['unbroken']}/{pm['blocks']} rounds unbroken, "
                     f"{min(spr):.1f}–{max(spr):.1f} s/rep" if spr else f"- {m}")
    if res["flags"]:
        lines.append("\n**Needs a look**")
        for f in res["flags"]:
            if "movement" in f:
                lines.append(f"- Round {f['round']} {f['movement']}: counted {f['detected']}, workout says {f['expected']} "
                             f"({mmss(f['start'])}–{mmss(f['end'])} in the video). Review frames: {f.get('frames_dir', '-')}")
            else:
                lines.append(f"- {f['why']}")
    if res.get("unsupported_movements"):
        lines.append(f"\n_Not yet in the movement library (not tracked): {', '.join(res['unsupported_movements'])}_")
    return "\n".join(lines)


def review_frames(video, flag, out_dir, n=4):
    """Save n frames across a flagged window for a vision model (or you) to check."""
    out = Path(out_dir) / f"r{flag['round']}_{flag['movement'].replace(' ', '_')}"
    out.mkdir(parents=True, exist_ok=True)
    a, b = flag["start"], flag["end"]
    for i in range(n):
        t = a + (b - a) * (i + 0.5) / n
        subprocess.run([_ff.exe(), "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-vf", "scale=-2:360",
                        "-frames:v", "1", str(out / f"{i}_{t:.1f}s.jpg")], check=False)
    flag["frames_dir"] = str(out)


def log_rows(res, video_name, workout_date=None):
    """Two kinds of rows: one per workout, one per round x movement."""
    d = workout_date or date.today().isoformat()
    sp, T = res["spec"], res["totals"]
    wid = f"{d}_{Path(video_name).stem}"
    workout = {"workout_id": wid, "date": d, "name": sp.get("name", ""), "format": sp.get("format", ""),
               "movements": "; ".join(f"{m.get('reps') or ''} {m['name']} {m.get('load', '')}".strip() for m in sp["movements"]),
               "score": T.get("score") or "", "rounds_complete": T["rounds_complete"], "elapsed_s": T["elapsed"],
               "moving_s": T["moving"], "between_s": T["between"], "between_pct": T["between_pct"],
               "flags": len([f for f in res["flags"] if "movement" in f]), "video": video_name}
    detail = []
    for r in res["rounds"]:
        for b in r["blocks"]:
            detail.append({"workout_id": wid, "date": d, "round": r["round"], "movement": b["movement"],
                           "reps": b["reps"], "expected": b.get("expected") or "", "sets": "+".join(map(str, b["sets"])),
                           "duration_s": b["duration"], "sec_per_rep": b["sec_per_rep"] or "",
                           "transition_after_s": b["transition_after"] if b["transition_after"] is not None else "",
                           "round_time_s": r["duration"], "flag": int(bool(b.get("flag")))})
    return workout, detail


def append_csv(path, rows):
    if not rows:
        return
    path = Path(path)
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if new:
            w.writeheader()
        w.writerows(rows)


def default(o):
    try:
        return float(o)
    except Exception:
        return str(o)


def save_json(res, path):
    json.dump(res, open(path, "w"), indent=1, default=default)
