"""Local workout database (SQLite) + raw-data archive.

Layout under $WOD_HOME (default ~/WODs):
  wod.db                         every number, queryable (see SCHEMA below)
  archive/<workout_id>/          the raw data, so a video never has to be processed twice
      pose.json.gz               body landmarks for every frame (the expensive part)
      audio.m4a                  16 kHz mono audio (rope clicks, beeps)
      workout.json               the workout as understood
      result.json                full analysis
      report.md                  human report
      thumb.jpg                  one frame for galleries
      source.json                original video name, path, fingerprint, length, recorded time

The database can always be rebuilt from the archive (`wod rebuild`), e.g. after the counting rules improve.
"""
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import statistics
from datetime import datetime
from pathlib import Path

ANALYZER_VERSION = "0.4.0"
WOD_HOME = Path(os.environ.get("WOD_HOME", Path.home() / "WODs"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS workouts(
  id TEXT PRIMARY KEY,              -- e.g. 2026-10-15_IMG_2787
  date TEXT,                        -- YYYY-MM-DD
  name TEXT, format TEXT,           -- amrap | for_time | rounds
  time_cap_s REAL, rounds_prescribed INTEGER,
  spec_json TEXT,                   -- the workout as parsed
  spec_hash TEXT,                   -- same workout repeated => same hash (benchmark WODs)
  video_name TEXT, video_path TEXT, video_fp TEXT UNIQUE, video_duration_s REAL, recorded_at TEXT,
  score TEXT, rounds_complete INTEGER, extra_reps INTEGER, total_reps INTEGER,
  elapsed_s REAL, moving_s REAL, between_s REAL, between_pct REAL,
  avg_hr REAL, notes TEXT, analyzer_version TEXT, analyzed_at TEXT, archive_dir TEXT);

CREATE TABLE IF NOT EXISTS movements(
  key TEXT PRIMARY KEY, name TEXT, cls TEXT, first_seen_date TEXT, first_seen_workout TEXT);

CREATE TABLE IF NOT EXISTS blocks(       -- one movement in one round
  id INTEGER PRIMARY KEY, workout_id TEXT, round INTEGER, seq INTEGER, pos_in_round INTEGER,
  movement_key TEXT, movement_name TEXT, load TEXT,
  start_s REAL, end_s REAL, duration_s REAL, work_s REAL, rest_inside_s REAL,
  reps INTEGER, expected INTEGER, n_sets INTEGER, sets TEXT, breaks_json TEXT,
  sec_per_rep REAL, reps_per_sec REAL, reps_per_min REAL,
  transition_after_s REAL, next_movement TEXT,
  round_complete INTEGER, flagged INTEGER, corrected INTEGER, audio_clicks INTEGER, avg_hr REAL);

CREATE TABLE IF NOT EXISTS sets(
  id INTEGER PRIMARY KEY, block_id INTEGER, workout_id TEXT, movement_key TEXT, round INTEGER,
  set_idx INTEGER, start_s REAL, end_s REAL, reps INTEGER, sec_per_rep REAL);

CREATE TABLE IF NOT EXISTS reps(          -- every single rep's timestamp
  workout_id TEXT, block_id INTEGER, movement_key TEXT, round INTEGER, set_idx INTEGER,
  rep_in_block INTEGER, rep_in_workout INTEGER, t_s REAL, since_prev_s REAL);

CREATE TABLE IF NOT EXISTS fresh_benchmarks(   -- round-1 speed per movement per workout
  movement_key TEXT, workout_id TEXT, date TEXT,
  round1_reps INTEGER, round1_duration_s REAL,
  reps_used INTEGER, time_for_10_s REAL, estimated INTEGER,   -- estimated=1 when round 1 had < 10 reps
  reps_per_sec REAL, unbroken INTEGER, first_time_seen INTEGER,
  PRIMARY KEY(movement_key, workout_id));

CREATE TABLE IF NOT EXISTS corrections(        -- your fixes; re-applied on every re-analysis
  id INTEGER PRIMARY KEY, workout_id TEXT, round INTEGER, movement_key TEXT,
  field TEXT, value TEXT, note TEXT, created_at TEXT);

CREATE INDEX IF NOT EXISTS ix_blocks_w ON blocks(workout_id);
CREATE INDEX IF NOT EXISTS ix_blocks_m ON blocks(movement_key);
CREATE INDEX IF NOT EXISTS ix_reps_w ON reps(workout_id);

-- ---------- views: ready-made answers ----------
DROP VIEW IF EXISTS v_movement_summary;
CREATE VIEW v_movement_summary AS
SELECT m.key AS movement_key, m.name AS movement, m.first_seen_date,
  COALESCE(MAX(b.unit), 'reps') AS unit,             -- reps, cal, ft or m
  COUNT(DISTINCT b.workout_id) AS workouts, SUM(b.reps) AS total_reps,   -- in the unit above
  ROUND(SUM(b.reps) / NULLIF(SUM(b.duration_s), 0), 3) AS avg_reps_per_sec,
  ROUND(SUM(b.duration_s) / NULLIF(SUM(b.reps), 0), 2) AS avg_sec_per_rep,
  (SELECT ROUND(MIN(time_for_10_s), 1) FROM fresh_benchmarks f WHERE f.movement_key = m.key) AS best_fresh_10_s,
  (SELECT ROUND(time_for_10_s, 1) FROM fresh_benchmarks f WHERE f.movement_key = m.key ORDER BY date DESC LIMIT 1) AS latest_fresh_10_s,
  (SELECT ROUND(AVG(time_for_10_s), 1) FROM fresh_benchmarks f WHERE f.movement_key = m.key) AS avg_fresh_10_s,
  (SELECT MAX(s.reps) FROM sets s JOIN blocks bb ON bb.id = s.block_id
     WHERE s.movement_key = m.key AND COALESCE(bb.counted, 1) = 1) AS biggest_unbroken_set
FROM movements m LEFT JOIN blocks b ON b.movement_key = m.key
GROUP BY m.key;

DROP VIEW IF EXISTS v_fatigue;          -- how much each movement slowed from round 1 to the last full round
CREATE VIEW v_fatigue AS
WITH r AS (
  SELECT b.workout_id, b.movement_key, b.movement_name, b.round, b.reps_per_sec,
         MIN(b.round) OVER (PARTITION BY b.workout_id, b.movement_key) AS first_r,
         MAX(CASE WHEN b.round_complete = 1 THEN b.round END) OVER (PARTITION BY b.workout_id, b.movement_key) AS last_r
  FROM blocks b)
SELECT w.date, r.workout_id, r.movement_name AS movement,
  MAX(CASE WHEN r.round = r.first_r THEN r.reps_per_sec END) AS first_round_reps_per_sec,
  MAX(CASE WHEN r.round = r.last_r THEN r.reps_per_sec END) AS last_round_reps_per_sec,
  ROUND(100.0 * (MAX(CASE WHEN r.round = r.last_r THEN r.reps_per_sec END)
        / NULLIF(MAX(CASE WHEN r.round = r.first_r THEN r.reps_per_sec END), 0) - 1), 1) AS pace_change_pct
FROM r JOIN workouts w ON w.id = r.workout_id
GROUP BY r.workout_id, r.movement_key;

DROP VIEW IF EXISTS v_transitions;      -- time between one movement and the next
CREATE VIEW v_transitions AS
SELECT movement_name AS from_movement, next_movement AS to_movement,
  COUNT(*) AS times, ROUND(AVG(transition_after_s), 1) AS avg_s,
  ROUND(MIN(transition_after_s), 1) AS best_s, ROUND(MAX(transition_after_s), 1) AS worst_s
FROM blocks WHERE transition_after_s IS NOT NULL GROUP BY movement_name, next_movement;

DROP VIEW IF EXISTS v_round_trend;      -- round times within each workout
CREATE VIEW v_round_trend AS
SELECT w.date, b.workout_id, b.round, ROUND(MAX(b.end_s) - MIN(b.start_s), 1) AS round_s,
  ROUND(SUM(b.duration_s), 1) AS moving_s, ROUND(SUM(COALESCE(b.transition_after_s, 0)), 1) AS transitions_s
FROM blocks b JOIN workouts w ON w.id = b.workout_id GROUP BY b.workout_id, b.round;

DROP VIEW IF EXISTS v_weekly_volume;
CREATE VIEW v_weekly_volume AS
SELECT strftime('%Y-W%W', w.date) AS week, b.movement_name AS movement, SUM(b.reps) AS reps,
  ROUND(SUM(b.duration_s) / 60.0, 1) AS minutes
FROM blocks b JOIN workouts w ON w.id = b.workout_id GROUP BY week, b.movement_key ORDER BY week;

DROP VIEW IF EXISTS v_repeats;          -- the same workout done more than once
CREATE VIEW v_repeats AS
SELECT spec_hash, name, date, id AS workout_id, score, elapsed_s, between_pct
FROM workouts WHERE spec_hash IN (SELECT spec_hash FROM workouts GROUP BY spec_hash HAVING COUNT(*) > 1)
ORDER BY spec_hash, date;
"""


MIGRATIONS = [  # columns added after the first release; safe to re-run
    "ALTER TABLE blocks ADD COLUMN unit TEXT",
    "ALTER TABLE blocks ADD COLUMN counted INTEGER",
    "ALTER TABLE blocks ADD COLUMN label TEXT",
    "ALTER TABLE workouts ADD COLUMN rest_s REAL",
    "ALTER TABLE workouts ADD COLUMN mode TEXT",
    "ALTER TABLE fresh_benchmarks ADD COLUMN unit TEXT",
]


def connect(home=None):
    home = Path(home or WOD_HOME)
    home.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(home / "wod.db")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    for m in MIGRATIONS:
        try:
            con.execute(m)
        except sqlite3.OperationalError:
            pass
    con.execute("INSERT OR REPLACE INTO meta VALUES('schema_version', ?)", (ANALYZER_VERSION,))
    return con


# ---------------------------------------------------------------- identity
def fingerprint(path, chunk=4 << 20):
    """Fast, stable id for a video file: size + first and last 4 MB."""
    p = Path(path)
    size = p.stat().st_size
    h = hashlib.sha1(str(size).encode())
    with open(p, "rb") as f:
        h.update(f.read(chunk))
        if size > chunk:
            f.seek(max(0, size - chunk))
            h.update(f.read(chunk))
    return h.hexdigest()[:20]


def spec_hash(spec):
    mv = [(m.get("key") or m["name"].lower(), m.get("reps"), (m.get("load") or "").lower()) for m in spec["movements"]]
    core = json.dumps([spec.get("format"), spec.get("time_cap_s"), spec.get("rounds"), spec.get("rep_scheme"), mv], sort_keys=True)
    return hashlib.sha1(core.encode()).hexdigest()[:12]


def find_by_fp(con, fp):
    r = con.execute("SELECT id, archive_dir FROM workouts WHERE video_fp = ?", (fp,)).fetchone()
    return dict(r) if r else None


def workout_id_for(date, video_name):
    return f"{date}_{re.sub(r'[^A-Za-z0-9_-]+', '_', Path(video_name).stem)}"


# ---------------------------------------------------------------- archive
def archive_dir(wid, home=None):
    return Path(home or WOD_HOME) / "archive" / wid


def save_archive(wid, work_dir, source, home=None):
    """Copy the expensive raw data into the archive (pose gzipped, audio compressed)."""
    import subprocess
    d = archive_dir(wid, home)
    d.mkdir(parents=True, exist_ok=True)
    work_dir = Path(work_dir)
    pj = work_dir / "pose.json"
    if pj.exists() and not (d / "pose.json.gz").exists():
        with open(pj, "rb") as f, gzip.open(d / "pose.json.gz", "wb", compresslevel=6) as g:
            shutil.copyfileobj(f, g)
    wav = work_dir / "audio.wav"
    if wav.exists() and not (d / "audio.m4a").exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-c:a", "aac", "-b:a", "48k", str(d / "audio.m4a")], check=False)
    for name in ("workout.json", "result.json", "report.md"):
        if (work_dir / name).exists():
            shutil.copy2(work_dir / name, d / name)
    small = work_dir / "small.mp4"
    if small.exists() and not (d / "thumb.jpg").exists():
        dur = source.get("video_duration_s") or 10
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{dur * 0.3:.1f}", "-i", str(small), "-vf", "scale=-2:360",
                        "-frames:v", "1", str(d / "thumb.jpg")], check=False)
    rv = work_dir / "review"
    if rv.exists():
        shutil.copytree(rv, d / "review", dirs_exist_ok=True)
    json.dump(source, open(d / "source.json", "w"), indent=1)
    return d


def load_pose(d):
    d = Path(d)
    if (d / "pose.json.gz").exists():
        return json.load(gzip.open(d / "pose.json.gz", "rt"))
    return json.load(open(d / "pose.json"))


def audio_wav(d, tmp_dir):
    """Decode the archived audio to a wav the analyzer can read (cached in tmp_dir)."""
    import subprocess
    d = Path(d)
    if (d / "audio.wav").exists():
        return str(d / "audio.wav")
    if not (d / "audio.m4a").exists():
        return None
    out = Path(tmp_dir) / "audio.wav"
    if not out.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(d / "audio.m4a"), "-ac", "1", "-ar", "16000", str(out)], check=True)
    return str(out)


# ---------------------------------------------------------------- corrections
def apply_corrections(con, wid, res):
    """Your manual fixes win over the tracker. Recomputes pace for corrected blocks."""
    rows = con.execute("SELECT * FROM corrections WHERE workout_id = ? ORDER BY id", (wid,)).fetchall()
    for c in rows:
        for r in res["rounds"]:
            if c["round"] is not None and r["round"] != c["round"]:
                continue
            for b in r["blocks"]:
                if c["movement_key"] not in (b["key"], b["movement"]):
                    continue
                if c["field"] == "reps":
                    b["reps"] = int(c["value"])
                    b["sec_per_rep"] = round(b["duration"] / b["reps"], 2) if b["reps"] else None
                    b["corrected"] = True
                    b.pop("flag", None)
    if rows:
        fixed = {(r["round"], b["movement"]) for r in res["rounds"] for b in r["blocks"] if b.get("corrected")}
        res["flags"] = [f for f in res["flags"] if (f.get("round"), f.get("movement")) not in fixed]
    return res


def add_correction(con, wid, round_, movement, field, value, note=""):
    con.execute("INSERT INTO corrections(workout_id, round, movement_key, field, value, note, created_at) VALUES(?,?,?,?,?,?,?)",
                (wid, round_, movement, field, str(value), note, datetime.now().isoformat(timespec="seconds")))
    con.commit()


# ---------------------------------------------------------------- write a workout
def _fresh(blocks, first_time):
    """Round-1 speed for one movement: working time for the first 10 reps (or 10 calories / 10 ft / 10 m).

    Counted movements add up the time spent in each set (not the walking between them) until 10 reps;
    with fewer than 10 reps in round 1 it is scaled up from the reps there were (estimated=1).
    Timed movements (bike, row, carry) use the prescribed amount over the time it took."""
    b0 = blocks[0]
    unit = b0.get("unit") or "reps"
    if b0.get("hidden"):
        return None          # athlete wasn't visible enough to time this movement fairly
    if b0.get("counted") is False:
        if not b0.get("reps") or not b0["duration"]:
            return None
        return {"round1_reps": b0["reps"], "round1_duration_s": b0["duration"], "reps_used": b0["reps"],
                "time_for_10_s": round(b0["duration"] / b0["reps"] * 10, 1), "estimated": 0,
                "reps_per_sec": round(b0["reps"] / b0["duration"], 3), "unbroken": 1, "first_time_seen": int(first_time), "unit": unit}
    gaps = [b - a for blk in blocks for s in blk["set_details"] for a, b in zip(s["rep_times"], s["rep_times"][1:])]
    med = statistics.median(gaps) if gaps else None
    acc, reps = 0.0, 0
    for blk in blocks:
        for s in blk["set_details"]:
            n = len(s["rep_times"])
            if not n:
                continue
            work = (s["rep_times"][-1] - s["rep_times"][0] + med) if (n >= 2 and med) else (s["end"] - s["start"])
            take = min(n, 10 - reps)
            acc += work * take / n
            reps += take
            if reps >= 10:
                break
        if reps >= 10:
            break
    if not reps or acc <= 0:
        return None
    t10 = acc if reps >= 10 else acc / reps * 10
    return {"round1_reps": sum(b["reps"] for b in blocks), "round1_duration_s": round(sum(b["duration"] for b in blocks), 1),
            "reps_used": reps, "time_for_10_s": round(t10, 1), "estimated": int(reps < 10),
            "reps_per_sec": round(reps / acc, 3), "unbroken": int(all(len(b["sets"]) == 1 for b in blocks)),
            "first_time_seen": int(first_time), "unit": unit}


def store(con, wid, res, source, archive, date, hr_by_round=None):
    """Replace everything stored for this workout with this analysis."""
    from .movements import LIBRARY
    sp, T = res["spec"], res["totals"]
    con.execute("DELETE FROM blocks WHERE workout_id = ?", (wid,))
    con.execute("DELETE FROM sets WHERE workout_id = ?", (wid,))
    con.execute("DELETE FROM reps WHERE workout_id = ?", (wid,))
    con.execute("DELETE FROM fresh_benchmarks WHERE workout_id = ?", (wid,))
    total_reps = sum(b["reps"] for r in res["rounds"] for b in r["blocks"])
    con.execute("""INSERT OR REPLACE INTO workouts(id, date, name, format, time_cap_s, rounds_prescribed, spec_json, spec_hash,
        video_name, video_path, video_fp, video_duration_s, recorded_at, score, rounds_complete, extra_reps, total_reps,
        elapsed_s, moving_s, between_s, between_pct, avg_hr, notes, analyzer_version, analyzed_at, archive_dir)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
               COALESCE((SELECT notes FROM workouts WHERE id = ?), NULL),?,?,?)""",
                (wid, date, sp.get("name"), sp.get("format"), sp.get("time_cap_s"), sp.get("rounds"),
                 json.dumps(sp), spec_hash(sp), source.get("video_name"), source.get("video_path"), source.get("video_fp"),
                 source.get("video_duration_s"), source.get("recorded_at"), T.get("score"), T["rounds_complete"],
                 T["extra_reps"], total_reps, T["elapsed"], T["moving"], T["between"], T["between_pct"],
                 (sum(hr_by_round.values()) / len(hr_by_round)) if hr_by_round else None,
                 wid, ANALYZER_VERSION, datetime.now().isoformat(timespec="seconds"), str(archive)))
    con.execute("UPDATE workouts SET rest_s = ?, mode = ? WHERE id = ?", (sp.get("rest_s"), res.get("mode", "standard"), wid))
    seq, rep_in_workout = 0, {}
    round1 = {}
    if res["rounds"]:
        for b in res["rounds"][0]["blocks"]:
            round1.setdefault(b["key"], []).append(b)
    for r in res["rounds"]:
        for pos, b in enumerate(r["blocks"]):
            seq += 1
            key = b["key"]
            known = con.execute("SELECT first_seen_date FROM movements WHERE key = ?", (key,)).fetchone()
            first_time = known is None or known["first_seen_date"] == date
            if known is None:
                con.execute("INSERT INTO movements VALUES(?,?,?,?,?)", (key, b["movement"], LIBRARY.get(key, {}).get("cls"), date, wid))
            nxt = r["blocks"][pos + 1]["movement"] if pos + 1 < len(r["blocks"]) else None
            if nxt is None:
                later = [rr for rr in res["rounds"] if rr["round"] == r["round"] + 1]
                nxt = later[0]["blocks"][0]["movement"] if later and later[0]["blocks"] else None
            work = sum(s["end"] - s["start"] for s in b["set_details"])
            rps = round(b["reps"] / b["duration"], 3) if b["duration"] else None
            cur = con.execute("""INSERT INTO blocks(workout_id, round, seq, pos_in_round, movement_key, movement_name, load,
                start_s, end_s, duration_s, work_s, rest_inside_s, reps, expected, n_sets, sets, breaks_json,
                sec_per_rep, reps_per_sec, reps_per_min, transition_after_s, next_movement, round_complete, flagged, corrected,
                audio_clicks, avg_hr) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (wid, r["round"], seq, pos + 1, key, b["movement"], b.get("load"), b["start"], b["end"], b["duration"],
                 round(work, 1), round(b["duration"] - work, 1), b["reps"], b.get("expected"), len(b["sets"]),
                 "+".join(map(str, b["sets"])), json.dumps(b["breaks"]), b["sec_per_rep"], rps,
                 round(rps * 60, 1) if rps else None, b["transition_after"], nxt if b["transition_after"] is not None else None,
                 int(r["complete"]), int(bool(b.get("flag"))), int(bool(b.get("corrected"))), b.get("audio_clicks"),
                 (hr_by_round or {}).get(r["round"])))
            bid = cur.lastrowid
            con.execute("UPDATE blocks SET unit = ?, counted = ?, label = ? WHERE id = ?",
                        (b.get("unit", "reps"), int(b.get("counted", True)), b.get("label") or b["movement"], bid))
            k = 0
            for si, s in enumerate(b["set_details"], 1):
                spr = round((s["end"] - s["start"]) / s["reps"], 2) if s["reps"] else None
                con.execute("INSERT INTO sets(block_id, workout_id, movement_key, round, set_idx, start_s, end_s, reps, sec_per_rep) VALUES(?,?,?,?,?,?,?,?,?)",
                            (bid, wid, key, r["round"], si, s["start"], s["end"], s["reps"], spr))
                prev = None
                for t in s["rep_times"]:
                    k += 1
                    rep_in_workout[key] = rep_in_workout.get(key, 0) + 1
                    con.execute("INSERT INTO reps VALUES(?,?,?,?,?,?,?,?,?)",
                                (wid, bid, key, r["round"], si, k, rep_in_workout[key], t, round(t - prev, 2) if prev is not None else None))
                    prev = t
    for key, blks in round1.items():
        first_time = con.execute("SELECT first_seen_workout FROM movements WHERE key = ?", (key,)).fetchone()["first_seen_workout"] == wid
        f = _fresh(blks, first_time)
        if f:
            con.execute("""INSERT OR REPLACE INTO fresh_benchmarks(movement_key, workout_id, date, round1_reps, round1_duration_s,
                reps_used, time_for_10_s, estimated, reps_per_sec, unbroken, first_time_seen, unit) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (key, wid, date, f["round1_reps"], f["round1_duration_s"], f["reps_used"], f["time_for_10_s"],
                         f["estimated"], f["reps_per_sec"], f["unbroken"], f["first_time_seen"], f["unit"]))
    con.commit()


def ingest(con, wid, res, source, work_dir, date, hr_by_round=None, home=None):
    res = json.loads(json.dumps(res, default=float))   # plain Python numbers for SQLite
    res = apply_corrections(con, wid, res)
    d = save_archive(wid, work_dir, source, home)
    json.dump(res, open(d / "result.json", "w"), indent=1, default=float)
    store(con, wid, res, source, d, date, hr_by_round)
    return d


# ---------------------------------------------------------------- read helpers
def query(con, sql, params=()):
    cur = con.execute(sql, params)
    cols = [c[0] for c in cur.description] if cur.description else []
    return cols, [tuple(r) for r in cur.fetchall()]


def fmt_table(cols, rows, max_rows=200):
    if not cols:
        return "(no result)"
    rows = rows[:max_rows]
    s = [[("" if v is None else str(v)) for v in r] for r in rows]
    w = [max(len(c), *(len(r[i]) for r in s)) if s else len(c) for i, c in enumerate(cols)]
    line = " | ".join(c.ljust(w[i]) for i, c in enumerate(cols))
    out = [line, "-+-".join("-" * x for x in w)]
    out += [" | ".join(r[i].ljust(w[i]) for i in range(len(cols))) for r in s]
    return "\n".join(out)
