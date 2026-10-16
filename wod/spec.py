"""Workout spec: parse the whiteboard text into structured JSON.

Spec format (JSON):
{
  "name": "Conditioning 1",
  "format": "amrap" | "for_time" | "rounds",
  "time_cap_s": 480,          # AMRAP length or for-time cap (optional)
  "rounds": 5,                # for "N rounds for time" (optional)
  "movements": [
     {"name": "Double Unders", "key": "double_under", "reps": 36},
     {"name": "Toes to Bar", "key": "toes_to_bar", "reps": 6},
     {"name": "Power Snatch", "key": "power_snatch", "reps": 6, "load": "95/65 lb"}
  ],
  "rep_scheme": [21, 15, 9]   # optional: per-round reps that override movement reps
}
"""
import json
import re

from .movements import lookup


def _secs(s):
    if ":" in s:
        m, sec = s.split(":")
        return int(m) * 60 + int(sec)
    return int(float(s) * 60)


def parse_text(text):
    spec = {"name": "", "format": "for_time", "movements": []}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        m = re.search(r"amrap\s*(?:in\s*)?(\d+(?::\d\d)?)", low) or re.search(r"(\d+(?::\d\d)?)\s*(?:min(?:ute)?s?)?\s*amrap", low)
        if m:
            spec["format"], spec["time_cap_s"] = "amrap", _secs(m.group(1))
            continue
        m = re.match(r"^(\d+)\s*(?:rounds?|rft)\b", low)
        if m:
            spec["format"], spec["rounds"] = "rounds", int(m.group(1))
            continue
        m = re.match(r"^(\d+(?:-\d+)+)\b", low)
        if m:
            spec["rep_scheme"] = [int(x) for x in m.group(1).split("-")]
            spec["rounds"] = len(spec["rep_scheme"])
            continue
        m = re.search(r"(?:time cap|cap)[: ]*(\d+(?::\d\d)?)", low)
        if m:
            spec["time_cap_s"] = _secs(m.group(1))
            continue
        if "for time" in low:
            spec["format"] = "rounds" if "rounds" in spec else "for_time"
            continue
        m = re.match(r"^rest\s*[:\-]?\s*(\d+(?::\d\d)?)\s*(?:min|minutes?|s|sec|seconds?)?\b", low)
        if m:
            v = m.group(1)
            spec["rest_s"] = _secs(v) if (":" in v or "min" in low) else int(v)
            continue
        # notes, scaling, links and headers aren't movements
        if line.startswith(("-", "•", "http")) or re.match(r"^(athlete notes|notes|duration|feel|pacing|scaling|equipment|warm ?up|stimulus|score|coach)", low):
            continue
        m = re.match(r"^(\d+(?:\.\d+)?)(?:\s*/\s*(\d+(?:\.\d+)?))?\s*(ft|feet|foot|m|meters?|metres?|cal(?:orie)?s?|x)?\b\s*(.+)$", line, re.I)
        name_part = m.group(4) if m else line
        reps = float(m.group(1)) if m else None
        reps = int(reps) if reps is not None and reps == int(reps) else reps
        unit_raw = (m.group(3) or "").lower() if m else ""
        unit = ("ft" if unit_raw in ("ft", "feet", "foot") else "m" if unit_raw.startswith("m") else
                "cal" if unit_raw.startswith("cal") else "reps")
        if re.search(r"\bcal(orie)?s?\b", name_part, re.I):
            unit = "cal"
            name_part = re.sub(r"\bcal(orie)?s?\b", "", name_part, flags=re.I)
        load = None
        lm = re.search(r"(\d+(?:/\d+)?\s*(?:lbs?|kg|#|pood|s\b))", name_part, re.I)
        if lm:
            load = lm.group(1)
            name_part = name_part[:lm.start()]
        name_part = re.sub(r"[*()@]", "", name_part)
        name_part = re.sub(r"\s+", " ", name_part).strip(" -,")
        key = lookup(name_part)
        if key or reps:
            mv = {"name": name_part, "key": key, "reps": reps}
            if unit != "reps":
                mv["unit"] = unit
            if m and m.group(2):
                mv["reps_alt"] = m.group(2)
            if load:
                mv["load"] = load
            spec["movements"].append(mv)
        elif not spec["name"]:
            spec["name"] = line
    return spec


def load(path_or_text):
    s = str(path_or_text)
    if s.endswith(".json"):
        return json.load(open(s))
    if s.endswith(".txt"):
        return parse_text(open(s).read())
    return parse_text(s)
