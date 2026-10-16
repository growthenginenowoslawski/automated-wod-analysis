"""Workout-aware segmentation: find each movement's sets, group into rounds, count reps,
time the transitions, and self-check against what the workout says should happen."""
from .movements import LIBRARY, count_reps, detect_sets

CLASS_PRIORITY = ["hang", "rope", "overhead", "floor_to_shoulder", "machine", "carry"]
MAX_BREAK_IN_BLOCK = 40.0   # same movement, sets separated by <= this (and nothing else between) = one block


def _overlap(a, b):
    return min(a["end"], b["end"]) - max(a["start"], b["start"]) > 0.3


def needs_sequence_mode(spec):
    keys = [m.get("key") for m in spec["movements"] if m.get("key")]
    timed = any(LIBRARY.get(k, {}).get("counter") == "time_only" for k in keys)
    return len(keys) != len(set(keys)) or timed or bool(spec.get("rest_s"))


def analyze(sig, spec, audio=None):
    sig.loose_hang = any(m.get("key") == "muscle_up" for m in spec["movements"])
    if needs_sequence_mode(spec):
        from .sequence import analyze_sequence
        return analyze_sequence(sig, spec, audio)
    moves = spec["movements"]
    unknown = [m["name"] for m in moves if not m.get("key") or m["key"] not in LIBRARY]
    known = [m for m in moves if m.get("key") in LIBRARY]
    classes = []
    for m in known:
        c = LIBRARY[m["key"]]["cls"]
        if c not in classes:
            classes.append(c)

    # 1) detect sets per class, highest-priority classes claim time first
    sets, claimed = [], None
    import numpy as np
    claimed = np.zeros_like(sig.t, dtype=bool)
    for c in sorted(classes, key=CLASS_PRIORITY.index):
        found = detect_sets(sig, c, audio=audio, exclude=claimed)
        found = [s for s in found if not any(_overlap(s, o) for o in sets)]
        for s in found:
            claimed |= sig.idx(s["start"], s["end"])
        sets += found
    sets.sort(key=lambda s: s["start"])

    # 2) map class -> movement(s); if two movements share a class, alternate in spec order
    by_cls = {}
    for m in known:
        by_cls.setdefault(LIBRARY[m["key"]]["cls"], []).append(m)

    # 3) merge consecutive same-class sets into blocks
    blocks = []
    for s in sets:
        if blocks and blocks[-1]["cls"] == s["cls"] and s["start"] - blocks[-1]["end"] <= MAX_BREAK_IN_BLOCK:
            blocks[-1]["sets"].append(s)
            blocks[-1]["end"] = s["end"]
        else:
            blocks.append({"cls": s["cls"], "start": s["start"], "end": s["end"], "sets": [s]})

    # 4) assign movements + count reps
    cls_counter = {}
    for b in blocks:
        opts = by_cls[b["cls"]]
        i = cls_counter.get(b["cls"], 0)
        mv = opts[i % len(opts)]
        cls_counter[b["cls"]] = i + 1
        b["movement"], b["key"] = mv["name"], mv["key"]
        counter = LIBRARY[mv["key"]]["counter"]
        for s in b["sets"]:
            s["rep_times"] = count_reps(sig, s, counter)
            s["reps"] = len(s["rep_times"])
        b["reps"] = sum(s["reps"] for s in b["sets"])
        b["breaks"] = [round(b2["start"] - b1["end"], 1) for b1, b2 in zip(b["sets"], b["sets"][1:])]
        if b["cls"] == "rope" and audio is not None:
            b["audio_clicks"] = sum(s.get("audio_clicks", 0) for s in b["sets"])

    # drop tiny stray blocks (e.g. a single overhead stretch) when they don't fit the plan
    blocks = [b for b in blocks if b["reps"] >= 2 or b["end"] - b["start"] > 4]

    # 5) rounds: a new round starts when a movement repeats
    rounds, cur = [], []
    for b in blocks:
        if any(x["key"] == b["key"] for x in cur) and len(set(x["key"] for x in cur)) >= 1:
            rounds.append(cur)
            cur = []
        cur.append(b)
    if cur:
        rounds.append(cur)

    # 6) expected reps & self-checks
    scheme = spec.get("rep_scheme")
    flags = []
    out_rounds = []
    for ri, r in enumerate(rounds):
        rr = {"round": ri + 1, "start": r[0]["start"], "end": r[-1]["end"], "blocks": []}
        complete = len(set(b["key"] for b in r)) == len(known)
        rr["complete"] = complete
        for bi, b in enumerate(r):
            mv = next(m for m in known if m["key"] == b["key"])
            exp = scheme[ri] if scheme and ri < len(scheme) else mv.get("reps")
            nxt = r[bi + 1]["start"] if bi + 1 < len(r) else (rounds[ri + 1][0]["start"] if ri + 1 < len(rounds) else None)
            work = sum(s["end"] - s["start"] for s in b["sets"])
            entry = {
                "movement": b["movement"], "key": b["key"], "start": round(b["start"], 1), "end": round(b["end"], 1),
                "duration": round(b["end"] - b["start"], 1), "work": round(work, 1),
                "reps": b["reps"], "expected": exp, "sets": [s["reps"] for s in b["sets"]],
                "breaks": b["breaks"], "sec_per_rep": round((b["end"] - b["start"]) / b["reps"], 2) if b["reps"] else None,
                "transition_after": round(nxt - b["end"], 1) if nxt is not None else None,
            }
            entry["set_details"] = [{"start": round(float(s["start"]), 2), "end": round(float(s["end"]), 2),
                                     "reps": s["reps"], "rep_times": [round(float(x), 2) for x in s["rep_times"]]}
                                    for s in b["sets"]]
            entry["load"] = mv.get("load")
            if "audio_clicks" in b:
                entry["audio_clicks"] = b["audio_clicks"]
            is_last_block = (ri == len(rounds) - 1 and bi == len(r) - 1)
            if exp and b["reps"] != exp and not (is_last_block and b["reps"] < exp):
                tol = 0.12 if b["cls"] == "rope" else 0
                if abs(b["reps"] - exp) > tol * exp:
                    flags.append({"round": ri + 1, "movement": b["movement"], "detected": b["reps"], "expected": exp,
                                  "start": entry["start"], "end": entry["end"],
                                  "why": "rep count differs from the workout"})
                    entry["flag"] = True
            if b["cls"] == "rope" and audio is not None and b.get("audio_clicks") and abs(b["audio_clicks"] - b["reps"]) > 0.2 * max(b["reps"], 1):
                entry["audio_disagrees"] = True
            rr["blocks"].append(entry)
        rr["duration"] = round(rr["end"] - rr["start"], 1)
        out_rounds.append(rr)

    # 7) totals & score
    start = out_rounds[0]["start"] if out_rounds else 0
    end = out_rounds[-1]["end"] if out_rounds else 0
    work = sum(e["work"] for r in out_rounds for e in r["blocks"])
    full_rounds = sum(1 for r in out_rounds if r["complete"])
    partial = out_rounds[-1] if out_rounds and not out_rounds[-1]["complete"] else None
    extra_reps = sum(e["reps"] for e in partial["blocks"]) if partial else 0
    totals = {
        "start": round(start, 1), "end": round(end, 1), "elapsed": round(end - start, 1),
        "moving": round(work, 1), "between": round(end - start - work, 1),
        "between_pct": round(100 * (end - start - work) / max(end - start, 1), 0),
        "rounds_complete": full_rounds, "extra_reps": extra_reps,
        "score": f"{full_rounds} rounds + {extra_reps} reps" if spec.get("format") == "amrap" else None,
    }
    if spec.get("format") == "amrap" and spec.get("time_cap_s") and end - start < spec["time_cap_s"] - 20:
        flags.append({"why": f"video covers {round(end-start)}s of a {spec['time_cap_s']}s AMRAP - reps after the recording ends are not counted"})
    per_move = {}
    for r in out_rounds:
        for e in r["blocks"]:
            pm = per_move.setdefault(e["movement"], {"durations": [], "sec_per_rep": [], "unbroken": 0, "blocks": 0})
            pm["durations"].append(e["duration"])
            if e["sec_per_rep"]:
                pm["sec_per_rep"].append(e["sec_per_rep"])
            pm["blocks"] += 1
            pm["unbroken"] += int(len(e["sets"]) == 1)
    return {"spec": spec, "unsupported_movements": unknown, "rounds": out_rounds, "totals": totals,
            "per_movement": per_move, "flags": flags,
            "observed_order": [b["movement"] for b in rounds[0]] if rounds else []}
