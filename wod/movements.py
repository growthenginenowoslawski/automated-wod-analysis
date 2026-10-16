"""Movement library.

Each movement belongs to a *class* that the detector can find in the video, and has a
rep counter. To add a movement: add an entry to LIBRARY (and aliases), reusing a class
or writing a new detector in detect_sets().
"""
import numpy as np

from .features import cadence_runs, runs

# class -> human description (also used in reports)
CLASSES = {
    "rope": "jump rope (double/single unders)",
    "hang": "hanging from the pull-up bar",
    "overhead": "barbell/dumbbell taken overhead (lockout)",
    "floor_to_shoulder": "barbell from floor to shoulders",
}

LIBRARY = {
    "double_under":   {"cls": "rope", "counter": "rope_jumps", "aliases": ["du", "dus", "double under", "double unders", "double-unders"]},
    "single_under":   {"cls": "rope", "counter": "rope_jumps", "aliases": ["single under", "single unders", "singles", "jump rope"]},
    "toes_to_bar":    {"cls": "hang", "counter": "legs_up", "aliases": ["t2b", "ttb", "toes to bar", "toes-to-bar"]},
    "knees_to_elbow": {"cls": "hang", "counter": "legs_up", "aliases": ["k2e", "knees to elbow", "knees to elbows", "hanging knee raise", "knee raises"]},
    "pull_up":        {"cls": "hang", "counter": "pull", "aliases": ["pull up", "pull-ups", "pull ups", "pullups", "kipping pull-up", "butterfly pull-up"]},
    "chest_to_bar":   {"cls": "hang", "counter": "pull", "aliases": ["c2b", "chest to bar", "chest-to-bar pull-ups"]},
    "power_snatch":   {"cls": "overhead", "counter": "lockouts", "aliases": ["snatch", "power snatch", "squat snatch", "hang power snatch", "dumbbell snatch", "db snatch"]},
    "clean_and_jerk": {"cls": "overhead", "counter": "lockouts", "aliases": ["clean and jerk", "clean & jerk", "c&j", "ground to overhead", "g2oh"]},
    "shoulder_to_overhead": {"cls": "overhead", "counter": "lockouts", "aliases": ["s2oh", "shoulder to overhead", "push press", "push jerk", "split jerk", "strict press", "jerk", "behind the neck jerk", "behind the neck press"]},
    "thruster":       {"cls": "overhead", "counter": "lockouts", "aliases": ["thrusters"]},
    "muscle_up":      {"cls": "hang", "counter": "muscle_up", "aliases": ["muscle up", "muscle ups", "muscle-up", "muscle-ups", "ring muscle up", "ring muscle ups", "bar muscle up", "bar muscle ups", "bmu", "rmu"]},
    "carry":          {"cls": "carry", "counter": "time_only", "aliases": ["sandbag carry", "sb carry", "farmers carry", "farmer carry", "farmer's carry", "front rack carry", "kb front rack carry", "yoke carry", "carry"]},
    "bike":           {"cls": "machine", "counter": "time_only", "aliases": ["c2 bike", "bike erg", "bikeerg", "echo bike", "assault bike", "air bike", "bike"]},
    "row":            {"cls": "machine", "counter": "time_only", "aliases": ["row", "rower", "c2 row", "rowing"]},
    "ski":            {"cls": "machine", "counter": "time_only", "aliases": ["ski", "ski erg", "skierg", "ski-erg"]},
    "power_clean":    {"cls": "floor_to_shoulder", "counter": "racks", "aliases": ["clean", "cleans", "power cleans", "squat clean", "hang power clean", "hang clean"]},
}


def lookup(name):
    n = name.lower().strip().rstrip("s") if name.lower().strip() not in ("dus",) else "dus"
    for key, m in LIBRARY.items():
        if name.lower().strip() in m["aliases"] or n in [a.rstrip("s") for a in m["aliases"]] or n == key.replace("_", " "):
            return key
    # loose contains-match, longest alias first
    cands = sorted(((a, k) for k, m in LIBRARY.items() for a in m["aliases"]), key=lambda x: -len(x[0]))
    for a, k in cands:
        if a in name.lower():
            return k
    return None


# ---------------------------------------------------------------- detection
def _roll(x, fps, secs, how):
    import pandas as pd
    r = pd.Series(x).rolling(max(3, int(secs * fps)), center=True, min_periods=3)
    return (r.max() - r.min()).values if how == "range" else r.std().values


def detect_sets(sig, cls, audio=None, exclude=None):
    """Return list of sets: dict(start, end, reps, rep_times, extra) for one movement class."""
    excl = np.zeros_like(sig.t, dtype=bool) if exclude is None else exclude
    excl = excl | ~sig.valid
    out = []
    if cls == "hang":
        # hanging or supported on the bar/rings; the body is often partly hidden by the rig, so allow brief gaps
        if getattr(sig, "loose_hang", False):
            # muscle-ups: the athlete is often half hidden by the rig, so allow brief gaps and count
            # "feet well off the floor" as hanging too
            import pandas as pd
            seen = pd.Series(sig.present.astype(float)).rolling(int(sig.fps), center=True, min_periods=1).mean().values > 0.3
            mask = (((sig.wrist_over_head > 0.2) & (sig.ankle_lift > 0.3)) | (sig.ankle_lift > 1.5)) & seen & ~(exclude if exclude is not None else False)
        else:
            mask = (sig.wrist_over_head > 0.2) & (sig.ankle_lift > 0.3) & ~excl
        for a, b in runs(mask, sig.t, min_len=1.5, merge_gap=0.7):
            out.append({"start": a, "end": b})
    elif cls == "machine":
        # bike / rower / ski: the hips stay put while the legs keep cycling
        still = _roll(sig.hip_x, sig.fps, 2.0, "range") < 0.6
        cycling = _roll(sig.knee_lr, sig.fps, 2.0, "std") > 0.07
        mask = still & cycling & (sig.ankle_lift < 1.5) & sig.present & ~(exclude if exclude is not None else False)
        for a, b in runs(mask, sig.t, min_len=10, merge_gap=6):
            out.append({"start": a, "end": b})
    elif cls == "carry":
        # carries: travelling across the floor with the hands in front of the body (not overhead, not hanging)
        travel = _roll(sig.hip_x, sig.fps, 2.0, "range") > 2.0
        mask = travel & (sig.wrist_over_head < -0.3) & (sig.ankle_lift < 1.5) & sig.present & ~excl
        for a, b in runs(mask, sig.t, min_len=3, merge_gap=2.5):
            out.append({"start": a, "end": b})
    elif cls == "rope":
        jumps = sig.peaks(sig.hip_up_raw, prominence=0.04, min_gap=0.27, mask=~excl & (sig.wrist_over_shoulder < -0.4))
        for g in cadence_runs(list(jumps), 0.3, 0.85, min_count=5):
            s = {"start": g[0] - 0.25, "end": g[-1] + 0.25, "rep_times": g}
            if audio is not None:
                s["audio_clicks"] = int(len(audio.clicks(g[0] - 0.2, g[-1] + 0.2)))
            out.append(s)
    elif cls == "overhead":
        lock = sig.peaks(sig.wrist_over_head, height=-0.15, prominence=0.8, min_gap=1.2,
                         mask=~excl & (sig.ankle_lift < 0.6))
        for g in cadence_runs(list(lock), 0.8, 8.0, min_count=1):
            out.append({"start": g[0] - 1.5, "end": g[-1] + 0.5, "rep_times": g})
    elif cls == "floor_to_shoulder":
        racks = sig.peaks(sig.wrist_over_shoulder, height=-0.35, prominence=0.5, min_gap=1.2,
                          mask=~excl & (sig.wrist_over_head < 0.2))
        for g in cadence_runs(list(racks), 0.8, 8.0, min_count=1):
            out.append({"start": g[0] - 1.5, "end": g[-1] + 0.5, "rep_times": g})
    for s in out:
        s["cls"] = cls
    return out


def count_reps(sig, s, counter):
    a, b = s["start"], s["end"]
    if counter in ("rope_jumps", "lockouts", "racks"):
        return list(s["rep_times"])
    if counter == "legs_up":
        return list(sig.peaks(sig.feet_over_hip, a, b, height=-1.0, prominence=0.3, min_gap=1.3))
    if counter == "muscle_up":
        # each rep ends with the body above the bar/rings: feet at their highest while off the floor
        return list(sig.peaks(sig.ankle_lift, a, b, height=1.0, prominence=0.8, min_gap=1.8))
    if counter == "pull":
        # shoulders rise toward the wrists: wrist_over_shoulder minima
        return list(sig.peaks(-sig.wrist_over_shoulder, a, b, prominence=0.3, min_gap=1.0))
    return []
