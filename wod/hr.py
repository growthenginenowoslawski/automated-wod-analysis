"""Optional heart-rate overlay.

Accepts a CSV with a timestamp column and a bpm column (most HR export apps produce one),
or Apple Health's export.xml. You give the wall-clock time the video started
(the video's creation time is used by default) and we average HR per round.
"""
import csv
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta


def _parse_time(s):
    s = s.strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def load_samples(path):
    samples = []
    if str(path).endswith(".xml"):
        for _, el in ET.iterparse(path):
            if el.tag == "Record" and el.get("type") == "HKQuantityTypeIdentifierHeartRate":
                t = _parse_time(el.get("startDate"))
                if t:
                    samples.append((t, float(el.get("value"))))
            el.clear()
        return samples
    with open(path) as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return samples
    tcol = next(c for c in rows[0] if re.search(r"time|date", c, re.I))
    bcol = next(c for c in rows[0] if re.search(r"bpm|heart|hr", c, re.I))
    for r in rows:
        t = _parse_time(r[tcol])
        if t and r[bcol]:
            samples.append((t, float(r[bcol])))
    return samples


def per_round(samples, video_start, res):
    """video_start: datetime of t=0 in the video. Returns {round: avg_bpm} plus whole-workout stats."""
    out = {}
    if not samples:
        return out
    tz = samples[0][0].tzinfo
    if video_start.tzinfo is None and tz is not None:
        video_start = video_start.replace(tzinfo=tz)
    for r in res["rounds"]:
        a = video_start + timedelta(seconds=r["start"])
        b = video_start + timedelta(seconds=r["end"])
        v = [bpm for t, bpm in samples if a <= t <= b]
        if v:
            out[r["round"]] = round(sum(v) / len(v))
    return out
