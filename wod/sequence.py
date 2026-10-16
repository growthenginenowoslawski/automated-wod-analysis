"""Sequence mode: workouts where the order matters more than the movement list.

Used when a movement repeats inside a round (1-2-3-4 muscle-up ladders), when a movement is
timed rather than counted (bike calories, carry distance), or when there is prescribed rest
between rounds. Each detected block is matched to the next position in the written order;
a position that never shows up is reported as missing instead of shifting everything after it.
"""
import numpy as np

from .movements import LIBRARY, count_reps, detect_sets

MERGE_GAP = 25.0        # same-class pieces this close, with nothing else between, are one block
MIN_VISIBLE = 0.8       # below this share of frames with the athlete visible, a count is not trusted
ANCHOR_JOIN = 15.0      # anchor pieces this close are one effort even if something else was detected between
ANCHOR_ORDER = ["machine", "rope", "overhead", "floor_to_shoulder", "hang", "carry"]   # most to least reliable


def _cls(m):
    return LIBRARY[m["key"]]["cls"]


def analyze_sequence(sig, spec, audio=None):
    from .analyze import CLASS_PRIORITY, _overlap
    seq = [m for m in spec["movements"] if m.get("key") in LIBRARY]
    unknown = [m["name"] for m in spec["movements"] if m.get("key") not in LIBRARY]
    for i, m in enumerate(seq):
        m["_pos"] = i
    classes = sorted({_cls(m) for m in seq}, key=CLASS_PRIORITY.index)

    # 1) detect sets per class; higher-priority classes claim their time first
    sets, claimed = [], np.zeros_like(sig.t, dtype=bool)
    for c in classes:
        found = [s for s in detect_sets(sig, c, audio=audio, exclude=claimed) if not any(_overlap(s, o) for o in sets)]
        for s in found:
            claimed |= sig.idx(s["start"], s["end"])
        sets += found
    sets.sort(key=lambda s: s["start"])

    # 2) merge neighbouring same-class pieces into blocks
    blocks = []
    for s in sets:
        if blocks and blocks[-1]["cls"] == s["cls"] and s["start"] - blocks[-1]["end"] <= MERGE_GAP:
            blocks[-1]["sets"].append(s)
            blocks[-1]["end"] = s["end"]
        else:
            blocks.append({"cls": s["cls"], "start": s["start"], "end": s["end"], "sets": [s]})

    # 3) anchor on the most reliably detected movement class, then fill the steps between anchors
    n, rest_s = len(seq), spec.get("rest_s")
    max_rounds = spec.get("rounds") or 99
    anchor_cls = next((c for c in ANCHOR_ORDER if any(_cls(m) == c for m in seq)), None)
    A = [i for i, m in enumerate(seq) if _cls(m) == anchor_cls]
    anchors, others = [], []
    for b in blocks:
        if b["cls"] == anchor_cls:
            if anchors and b["start"] - anchors[-1]["end"] < ANCHOR_JOIN:   # one effort split by a short pause
                anchors[-1]["sets"] += b["sets"]
                anchors[-1]["end"] = b["end"]
            else:
                anchors.append(dict(b))
        else:
            others.append(b)
    # anchors -> (round, anchor position). A new round can't start sooner than the prescribed rest allows.
    rounds_a, k, ignored, last_end = [[]], 0, [], None
    for b in anchors:
        if k == len(A):
            if rest_s and last_end is not None and b["start"] - last_end < rest_s:
                ignored.append(b)             # too soon after the round ended: someone else, or a false detection
                continue
            rounds_a.append([])
            k = 0
        if len(rounds_a) > max_rounds:
            ignored.append(b)
            continue
        rounds_a[-1].append((A[k], b))
        k += 1
        last_end = b["end"]
    rounds = [dict((pos, b) for pos, b in ra) for ra in rounds_a if ra]

    def match(positions, pool):
        """Greedy in-order match of written steps to detected blocks (blocks of other classes are skipped)."""
        got, i = {}, 0
        for j, pos in enumerate(positions):
            c = _cls(seq[pos])
            nxt = _cls(seq[positions[j + 1]]) if j + 1 < len(positions) else None
            while i < len(pool) and pool[i]["cls"] != c:
                i += 1
            if i >= len(pool):
                break
            blk = dict(pool[i], sets=list(pool[i]["sets"]))
            i += 1
            while i < len(pool) and pool[i]["cls"] == c and c != nxt and abs(pool[i]["start"] - blk["end"]) < 30:
                blk["sets"] += pool[i]["sets"]
                blk["end"] = max(blk["end"], pool[i]["end"])
                blk["start"] = min(blk["start"], pool[i]["start"])
                i += 1
            got[pos] = blk
        return got

    def between(a, b):
        return [o for o in others if o["start"] >= a - 1 and o["end"] <= b + 1]

    t_end = float(sig.t[-1])
    for ri, r in enumerate(rounds):
        apos = sorted(r)
        # steps between consecutive anchors: matched backwards from the next anchor, because the walk
        # away from an anchor looks like a carry while the real steps lead straight into the next one
        for p1, p2 in zip(apos, apos[1:]):
            pool = between(r[p1]["end"], r[p2]["start"])
            got = match(list(range(p1 + 1, p2))[::-1], [dict(b, sets=b["sets"][::-1]) for b in pool[::-1]])
            for b in got.values():
                b["sets"] = b["sets"][::-1]
            r.update(got)
        # steps before the first anchor: matched backwards from the anchor (the rest sits before them)
        head = list(range(0, apos[0]))
        if head:
            lo = rounds[ri - 1][max(rounds[ri - 1])]["end"] if ri else 0.0
            pool = between(lo, r[apos[0]]["start"])
            got = match(head[::-1], [dict(b, sets=b["sets"][::-1]) for b in pool[::-1]])
            for pos, b in got.items():
                b["sets"] = b["sets"][::-1]
            r.update(got)
        # steps after the last anchor: matched forwards (the rest comes after them)
        tail = list(range(apos[-1] + 1, n))
        if tail:
            hi = rounds[ri + 1][min(rounds[ri + 1])]["start"] if ri + 1 < len(rounds) else t_end
            pool = between(r[apos[-1]]["end"], hi)
            if ri + 1 < len(rounds):
                # leave the next round's lead-in steps (found backwards) alone: stop at the longest quiet gap
                gaps = [(pool[i + 1]["start"] - pool[i]["end"], i) for i in range(len(pool) - 1)]
                if gaps:
                    g, gi = max(gaps)
                    if rest_s and g > 0.5 * rest_s:
                        pool = pool[:gi + 1]
            r.update(match(tail, pool))

    # 4) build round/block entries in the same shape as the standard analysis
    flags, out_rounds = [], []
    for ri, r in enumerate(rounds):
        entries = []
        for pos in range(n):
            m = seq[pos]
            if pos not in r:
                if ri < len(rounds) - 1 or pos < max(r):
                    flags.append({"round": ri + 1, "movement": m["name"], "detected": 0, "expected": m.get("reps"),
                                  "start": None, "end": None, "why": "not found in the video"})
                continue
            b = r[pos]
            info = LIBRARY[m["key"]]
            counted = info["counter"] != "time_only"
            seen = float(np.mean(sig.present[sig.idx(b["start"], b["end"])])) if b["end"] > b["start"] else 0.0
            hidden = counted and seen < MIN_VISIBLE
            if hidden:
                counted = False      # athlete mostly hidden (rig, another person): time it, don't guess the count
            for s in b["sets"]:
                s["rep_times"] = [float(x) for x in count_reps(sig, s, info["counter"])] if counted else []
                s["reps"] = len(s["rep_times"])
            if counted:
                b["sets"] = [s for s in b["sets"] if s["reps"] > 0] or b["sets"][:1]
                b["start"], b["end"] = b["sets"][0]["start"], b["sets"][-1]["end"]
            reps = sum(s["reps"] for s in b["sets"]) if counted else m.get("reps")
            dur = b["end"] - b["start"]
            work = sum(s["end"] - s["start"] for s in b["sets"])
            e = {"movement": m["name"], "key": m["key"], "position": pos + 1, "unit": m.get("unit", "reps"),
                 "label": f"{m.get('reps') or ''}{'ft' if m.get('unit') == 'ft' else 'm' if m.get('unit') == 'm' else ' cal' if m.get('unit') == 'cal' else ''} {m['name']}".strip(),
                 "counted": counted, "hidden": hidden, "visible_pct": round(100 * seen),
                 "start": round(float(b["start"]), 1), "end": round(float(b["end"]), 1),
                 "duration": round(float(dur), 1), "work": round(float(work), 1), "reps": reps, "expected": m.get("reps"),
                 "sets": [s["reps"] for s in b["sets"]] if counted else [reps],
                 "breaks": [round(float(s2["start"] - s1["end"]), 1) for s1, s2 in zip(b["sets"], b["sets"][1:])] if counted else [],
                 "sec_per_rep": round(dur / reps, 2) if reps else None, "load": m.get("load"),
                 "set_details": [{"start": round(float(s["start"]), 2), "end": round(float(s["end"]), 2), "reps": s["reps"],
                                  "rep_times": [round(x, 2) for x in s["rep_times"]]} for s in b["sets"]]}
            if counted and m.get("reps") and reps != m["reps"]:
                e["flag"] = True
                flags.append({"round": ri + 1, "movement": m["name"], "detected": reps, "expected": m["reps"],
                              "start": e["start"], "end": e["end"], "why": "rep count differs from the workout"})
            entries.append(e)
        for e1, e2 in zip(entries, entries[1:]):
            e1["transition_after"] = round(e2["start"] - e1["end"], 1)
        if entries:
            entries[-1]["transition_after"] = None
        complete = len(entries) == n
        rr = {"round": ri + 1, "start": entries[0]["start"] if entries else 0, "end": entries[-1]["end"] if entries else 0,
              "complete": complete, "blocks": entries}
        rr["duration"] = round(rr["end"] - rr["start"], 1)
        out_rounds.append(rr)
    for r1, r2 in zip(out_rounds, out_rounds[1:]):
        r1["rest_after"] = round(r2["start"] - r1["end"], 1)

    start = out_rounds[0]["start"] if out_rounds else 0
    end = out_rounds[-1]["end"] if out_rounds else 0
    moving = sum(e["duration"] for r in out_rounds for e in r["blocks"])
    rest_total = sum(r.get("rest_after", 0) for r in out_rounds)
    active = max(end - start - rest_total, 1)
    full = sum(1 for r in out_rounds if r["complete"])
    totals = {"start": start, "end": end, "elapsed": round(end - start, 1), "moving": round(moving, 1),
              "rest": round(rest_total, 1), "between": round(active - moving, 1),
              "between_pct": round(100 * (active - moving) / active, 0), "rounds_complete": full, "extra_reps": 0,
              "score": f"{len(out_rounds)} rounds, {int(active // 60)}:{int(active % 60):02d} working (excl. rest)"}
    if spec.get("rounds") and len(out_rounds) < spec["rounds"]:
        left = float(sig.t[-1]) - end
        why = (f"the video ends {int(left)}s after round {len(out_rounds)}, so {'round ' + str(spec['rounds']) + ' isn' if spec['rounds'] - len(out_rounds) == 1 else 'rounds ' + str(len(out_rounds) + 1) + '-' + str(spec['rounds']) + ' aren'}'t on it"
               if left < 180 else f"found {len(out_rounds)} of {spec['rounds']} rounds")
        flags.append({"why": why})
    if rest_s:
        short = [r for r in out_rounds if r.get("rest_after") and r["rest_after"] < 0.85 * rest_s]
        if short:
            flags.append({"why": "measured rest was shorter than the prescribed " + f"{int(rest_s // 60)}:{int(rest_s % 60):02d} after round(s) "
                          + ", ".join(str(r["round"]) for r in short) + "; either you started early, or the last step of the round ran long on video"})
    per_move = {}
    for r in out_rounds:
        for e in r["blocks"]:
            pm = per_move.setdefault(e["movement"], {"durations": [], "sec_per_rep": [], "unbroken": 0, "blocks": 0})
            pm["durations"].append(e["duration"])
            if e["sec_per_rep"]:
                pm["sec_per_rep"].append(e["sec_per_rep"])
            pm["blocks"] += 1
            pm["unbroken"] += int(len(e["sets"]) == 1)
    return {"spec": {k: v for k, v in spec.items()}, "mode": "sequence", "unsupported_movements": unknown,
            "rounds": out_rounds, "totals": totals, "per_movement": per_move, "flags": flags,
            "observed_order": [m["name"] for m in seq], "ignored_blocks": len(ignored)}
