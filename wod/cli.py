"""wod — analyze CrossFit workout videos and keep every number in a local database.

  wod setup                      one-time setup (model, folders, AI assistant instructions, inbox watcher)
  wod guide                      step-by-step instructions for AI assistants (Claude, Codex/ChatGPT…)

  wod analyze VIDEO --workout "AMRAP 8:00\\n36 Double Unders\\n6 Toes to Bar\\n6 Power Snatch"
        [--date 2026-10-15] [--hr heart.csv] [--notes "felt heavy"] [--force]
        A video that was already analyzed is recognized and NOT processed again (use --force to redo it).

  wod stats                      overview: every movement, fresh-10 benchmarks, reps/sec
  wod movement "power snatch"    one movement's history
  wod workout [ID|latest]        the report for one workout
  wod list                       all workouts
  wod sql "SELECT ..."           ask the database anything (read-only)
  wod schema                     tables and views you can query
  wod correct ID --round 2 --movement "Power Snatch" --reps 6 [--note ...]
                                 fix a count; kept forever and re-applied on every re-analysis
  wod note ID "text"             attach a note (how you felt, scaling, etc.)
  wod reanalyze [ID|--all]       re-run the counting from saved data (no video needed)
  wod rebuild                    rebuild the whole database from the archive
  wod dashboard                  write ~/WODs/dashboard.html and open it
  wod export                     CSV copies of every table in ~/WODs/export/
  wod parse "AMRAP 8 ..."        show how a workout text is understood
  wod summary [ID|latest]        compact text of one workout + history, for any chatbot
  wod watch [--inbox DIR]        process every video dropped into ~/WODs/inbox (Mac and Windows)
  wod doctor                     check that everything is installed
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from . import db as DB

HERE = Path(__file__).resolve().parent.parent


MODEL_URLS = {
    "full": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task",
    "lite": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
}
MODEL_URL = MODEL_URLS["full"]
MIRROR = "https://raw.githubusercontent.com/growthenginenowoslawski/automated-wod-analysis/main/models/{name}"


def find_model(download=True, kind="full"):
    name = f"pose_landmarker_{kind}.task"
    env = os.environ.get("WOD_POSE_MODEL") if kind == "full" else None
    for p in [env, DB.WOD_HOME / "models" / name, HERE / "models" / name, Path.home() / "Downloads" / name]:
        if p and Path(p).exists():
            return Path(p)
    if not download:
        return None
    dst = DB.WOD_HOME / "models" / name
    dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading the body-tracking model ({kind}, about {9 if kind == 'full' else 6} MB, once)…", flush=True)
    import urllib.request
    errors = []
    for url in (MODEL_URLS[kind], MIRROR.format(name=name)):     # Google first, then the copy in this project's repo
        try:
            tmp = dst.with_suffix(".part")
            urllib.request.urlretrieve(url, tmp)
            if tmp.stat().st_size < 1_000_000:
                raise IOError("download incomplete")
            tmp.replace(dst)
            return dst
        except Exception as e:
            errors.append(f"{url}: {e}")
    if download == "soft":
        return None
    sys.exit("Couldn't download the body-tracking model:\n  " + "\n  ".join(errors) +
             f"\nDownload it in a browser from {MODEL_URLS[kind]} and save it as {dst}")


def creation_time(video):
    try:
        from . import ff
        return ff.probe(video)["creation_time"]
    except Exception:
        return None


def _log(t0, quiet=False):
    if quiet:
        return lambda m: None
    return lambda m: print(f"[{time.time() - t0:5.0f}s] {m}", flush=True)


def tracking_fps(spec, fast=False):
    """15 frames/sec for everything. Tested: 10 frames/sec looked fine in simulation but made the real tracker
    lose the athlete more often, which broke machine detection on a 24-minute interval workout."""
    return 15


def _spec_from(a, video=None):
    from .spec import load
    if a.workout:
        return load(a.workout.replace("\\n", "\n"))
    if video:
        side = [video.with_suffix(".txt"), video.with_suffix(".json"), video.parent / "workout.txt"]
        found = next((p for p in side if p.exists()), None)
        if found:
            return load(found)
    sys.exit("Tell me the workout: --workout \"AMRAP 8 ...\" or put a .txt with the same name next to the video.")


def _run_analysis(sig_pose, spec, audio_path):
    from .analyze import analyze
    from .features import Audio, Signals
    sig = Signals(sig_pose)
    audio = Audio(audio_path) if audio_path else None
    return analyze(sig, spec, audio)


def _fresh_notes(con, wid):
    """Plain-language fresh-benchmark lines for the report."""
    lines = []
    rows = con.execute("SELECT f.*, m.name FROM fresh_benchmarks f JOIN movements m ON m.key = f.movement_key WHERE workout_id = ?",
                       (wid,)).fetchall()
    for f in rows:
        prev = con.execute("""SELECT MIN(time_for_10_s) AS best, COUNT(*) AS n FROM fresh_benchmarks
                              WHERE movement_key = ? AND date < (SELECT date FROM workouts WHERE id = ?)""",
                           (f["movement_key"], wid)).fetchone()
        unit = f["unit"] if "unit" in f.keys() and f["unit"] else "reps"
        est = f" (estimated from {f['reps_used']} reps)" if f["estimated"] else ""
        if unit == "cal":
            base = f"- {f['name']}: 10 cal fresh in {f['time_for_10_s']:.1f}s ({f['reps_per_sec'] * 60:.1f} cal/min in round 1)."
        elif unit in ("ft", "m"):
            base = f"- {f['name']}: {f['round1_reps']} {unit} in {f['round1_duration_s']:.1f}s in round 1."
        else:
            base = f"- {f['name']}: 10 reps fresh in {f['time_for_10_s']:.1f}s{est}, {f['reps_per_sec']:.2f} reps/sec in round 1."
        if f["first_time_seen"] or not prev["n"]:
            base += " New movement: this is your baseline."
        elif prev["best"]:
            d = f["time_for_10_s"] - prev["best"]
            base += f" Best before: {prev['best']:.1f}s ({'+' if d >= 0 else ''}{d:.1f}s)."
        lines.append(base)
    return lines


def _finish(con, wid, res, work_dir=None):
    from .report import to_markdown
    md = to_markdown(res)
    fresh = _fresh_notes(con, wid)
    if fresh:
        md += "\n\n**Fresh speed (round 1)**\n" + "\n".join(fresh)
    same = con.execute("""SELECT date, score, elapsed_s, between_pct FROM workouts
                          WHERE spec_hash = (SELECT spec_hash FROM workouts WHERE id = ?) AND id != ? ORDER BY date""", (wid, wid)).fetchall()
    if same:
        md += "\n\n**You've done this workout before**\n" + "\n".join(
            f"- {r['date']}: {r['score'] or ''} in {int(r['elapsed_s'] // 60)}:{int(r['elapsed_s'] % 60):02d}, {r['between_pct']:.0f}% between movements"
            for r in same)
    d = DB.archive_dir(wid)
    (d / "report.md").write_text(md)
    if work_dir:
        (Path(work_dir) / "report.md").write_text(md)
    return md


# ---------------------------------------------------------------- commands
def cmd_analyze(a):
    from . import prep
    from .pose import extract, make_factory
    from .report import review_frames
    video = Path(a.video).expanduser().resolve()
    con = DB.connect()
    t0 = time.time()
    log = _log(t0, a.quiet)
    log("fingerprinting video")
    fp = a.fingerprint or DB.fingerprint(video)
    hit = DB.find_by_fp(con, fp)
    if hit and not a.force:
        rep = Path(hit["archive_dir"]) / "report.md"
        print(f"Already analyzed as {hit['id']} — not processing again (use --force to redo, or `wod reanalyze {hit['id']}`).\n")
        print(rep.read_text() if rep.exists() else "")
        return
    spec = _spec_from(a, video)
    info = prep.probe(video)
    rec = creation_time(video)
    date = a.date or (rec or datetime.now()).date().isoformat()
    wid = hit["id"] if hit else DB.workout_id_for(date, video.name)
    work = DB.WOD_HOME / ".work" / fp
    work.mkdir(parents=True, exist_ok=True)
    json.dump(spec, open(work / "workout.json", "w"), indent=1)
    model = find_model(kind="lite" if a.fast else "full")
    factory = make_factory(model)
    small, pose_json = work / "small.mp4", work / "pose.json"
    if not pose_json.exists():
        rot, scores = prep.detect_rotation(video, factory)
        log(f"orientation: {rot}")
        fps = tracking_fps(spec, a.fast)
        prep.transcode(video, small, rotation=rot, fps=fps)
        log(f"video prepared ({fps} frames/sec)")
        from .pose import extract_parallel
        extract_parallel(small, model, pose_json, workers=a.workers, progress=lambda p: log(f"tracking body… {p:.0%}"))
        log("body tracking done")
    wav = None
    if info["has_audio"]:
        wav = work / "audio.wav"
        if not wav.exists():
            prep.extract_audio(video, wav)
    res = _run_analysis(json.load(open(pose_json)), spec, str(wav) if wav else None)
    # frames for the assistant to check: at most 3 flagged steps, and only ones that were visible
    # (a step hidden behind the rig won't get clearer by looking at it)
    for f in [f for f in res["flags"] if "movement" in f and f.get("start") is not None][:3]:
        if small.exists():
            review_frames(small, f, work / "review")
    hr = None
    if a.hr:
        from .hr import load_samples, per_round
        start = datetime.fromisoformat(a.video_start) if a.video_start else rec
        hr = per_round(load_samples(a.hr), start, res) if start else None
    source = {"video_name": video.name, "video_path": str(video), "video_fp": fp,
              "video_duration_s": info["duration"], "recorded_at": rec.isoformat() if rec else None}
    DB.ingest(con, wid, res, source, work, date, hr)
    if a.notes:
        con.execute("UPDATE workouts SET notes = ? WHERE id = ?", (a.notes, wid))
        con.commit()
    md = _finish(con, wid, json.load(open(DB.archive_dir(wid) / "result.json")), work)
    # the archive now holds everything; drop the big working copy
    if small.exists() and not res["flags"]:
        small.unlink()
    log(f"saved as {wid} → {DB.archive_dir(wid)}")
    print("\n" + md)


def _reanalyze_one(con, wid):
    import tempfile
    from .spec import load
    row = con.execute("SELECT * FROM workouts WHERE id = ?", (wid,)).fetchone()
    d = Path(row["archive_dir"]) if row else DB.archive_dir(wid)
    spec = json.load(open(d / "workout.json"))
    source = json.load(open(d / "source.json")) if (d / "source.json").exists() else {}
    date = row["date"] if row else wid[:10]
    with tempfile.TemporaryDirectory() as td:
        res = _run_analysis(DB.load_pose(d), spec, DB.audio_wav(d, td))
        res = DB.apply_corrections(con, wid, res)
        json.dump(res, open(d / "result.json", "w"), indent=1, default=float)
        DB.store(con, wid, json.load(open(d / "result.json")), source, d, date)
    return _finish(con, wid, json.load(open(d / "result.json")))


def cmd_reanalyze(a):
    con = DB.connect()
    ids = [r["id"] for r in con.execute("SELECT id FROM workouts ORDER BY date")] if a.all else [_resolve(con, a.id)]
    for wid in ids:
        md = _reanalyze_one(con, wid)
        print(f"re-analyzed {wid}")
        if not a.all:
            print("\n" + md)


def cmd_rebuild(a):
    dbp = DB.WOD_HOME / "wod.db"
    old = DB.connect()
    keep = [dict(r) for r in old.execute("SELECT * FROM corrections")]
    notes = {r["id"]: r["notes"] for r in old.execute("SELECT id, notes FROM workouts WHERE notes IS NOT NULL")}
    old.close()
    if dbp.exists():
        shutil.copy2(dbp, dbp.with_suffix(".db.bak"))
        dbp.unlink()
    con = DB.connect()
    for c in keep:
        con.execute("INSERT INTO corrections(workout_id, round, movement_key, field, value, note, created_at) VALUES(?,?,?,?,?,?,?)",
                    (c["workout_id"], c["round"], c["movement_key"], c["field"], c["value"], c["note"], c["created_at"]))
    con.commit()
    arch = sorted((DB.WOD_HOME / "archive").glob("*/workout.json"), key=lambda p: p.parent.name)
    for p in arch:
        _reanalyze_one(con, p.parent.name)
        print(f"rebuilt {p.parent.name}")
    for wid, n in notes.items():
        con.execute("UPDATE workouts SET notes = ? WHERE id = ?", (n, wid))
    con.commit()
    print(f"{len(arch)} workouts in the database (backup: {dbp.with_suffix('.db.bak')})")


def _resolve(con, wid):
    if not wid or wid == "latest":
        r = con.execute("SELECT id FROM workouts ORDER BY date DESC, analyzed_at DESC LIMIT 1").fetchone()
        if not r:
            sys.exit("No workouts yet.")
        return r["id"]
    r = con.execute("SELECT id FROM workouts WHERE id = ? OR id LIKE ? ORDER BY date DESC", (wid, f"%{wid}%")).fetchone()
    if not r:
        sys.exit(f"No workout matching {wid!r}. Try `wod list`.")
    return r["id"]


def cmd_correct(a):
    from .movements import lookup
    con = DB.connect()
    wid = _resolve(con, a.id)
    key = lookup(a.movement) or a.movement
    DB.add_correction(con, wid, a.round, key, "reps", a.reps, a.note or "")
    print(f"Saved: {wid} round {a.round or 'all'} {a.movement} = {a.reps} reps. Re-analyzing…")
    print(_reanalyze_one(con, wid))


def cmd_note(a):
    con = DB.connect()
    wid = _resolve(con, a.id)
    con.execute("UPDATE workouts SET notes = ? WHERE id = ?", (a.text, wid))
    con.commit()
    print(f"Note saved on {wid}.")


def cmd_workout(a):
    con = DB.connect()
    wid = _resolve(con, a.id)
    print((DB.archive_dir(wid) / "report.md").read_text())


def cmd_list(a):
    con = DB.connect()
    print(DB.fmt_table(*DB.query(con, """SELECT id, date, name, score, ROUND(elapsed_s/60.0,1) AS minutes,
        ROUND(between_pct) AS between_pct, total_reps, notes FROM workouts ORDER BY date DESC""")))


def cmd_stats(a):
    con = DB.connect()
    n = con.execute("SELECT COUNT(*), MIN(date), MAX(date), SUM(total_reps), ROUND(SUM(elapsed_s)/60.0) FROM workouts").fetchone()
    print(f"{n[0]} workouts ({n[1]} → {n[2]}), {n[3] or 0} reps, {n[4] or 0} minutes analyzed.\n")
    print("Movements (fresh 10 = time for 10 reps in round 1; avg reps/sec across every round):")
    print(DB.fmt_table(*DB.query(con, """SELECT movement, first_seen_date AS first_seen, workouts, total_reps AS total, unit,
        best_fresh_10_s, latest_fresh_10_s, avg_reps_per_sec, avg_sec_per_rep, biggest_unbroken_set FROM v_movement_summary
        ORDER BY total_reps DESC""")))
    print("\nSlowest transitions:")
    print(DB.fmt_table(*DB.query(con, "SELECT * FROM v_transitions ORDER BY avg_s DESC LIMIT 5")))
    print("\nPace change from first to last full round (negative = slowed down):")
    print(DB.fmt_table(*DB.query(con, "SELECT * FROM v_fatigue ORDER BY date DESC LIMIT 12")))


def cmd_movement(a):
    from .movements import lookup
    con = DB.connect()
    key = lookup(a.name) or a.name
    print(DB.fmt_table(*DB.query(con, "SELECT * FROM v_movement_summary WHERE movement_key = ?", (key,))))
    print("\nFresh (round 1) by workout:")
    print(DB.fmt_table(*DB.query(con, """SELECT date, workout_id, round1_reps, round1_duration_s, time_for_10_s,
        CASE estimated WHEN 1 THEN 'yes' ELSE '' END AS estimated, reps_per_sec, first_time_seen
        FROM fresh_benchmarks WHERE movement_key = ? ORDER BY date""", (key,))))
    print("\nEvery round:")
    print(DB.fmt_table(*DB.query(con, """SELECT w.date, b.round, b.reps, b.sets, b.duration_s, b.sec_per_rep, b.reps_per_sec,
        b.transition_after_s, b.load FROM blocks b JOIN workouts w ON w.id = b.workout_id
        WHERE b.movement_key = ? ORDER BY w.date, b.round""", (key,))))


def cmd_sql(a):
    p = DB.WOD_HOME / "wod.db"
    DB.connect().close()
    import sqlite3
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        cols, rows = DB.query(con, a.query)
    except sqlite3.Error as e:
        sys.exit(f"SQL error: {e}")
    if a.json:
        print(json.dumps([dict(zip(cols, r)) for r in rows], indent=1, default=str))
    else:
        print(DB.fmt_table(cols, rows, max_rows=a.limit))


def cmd_schema(a):
    con = DB.connect()
    for (name, sql) in con.execute("SELECT name, sql FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY type DESC, name"):
        print(sql + ";\n")


def cmd_export(a):
    import csv
    con = DB.connect()
    out = DB.WOD_HOME / "export"
    out.mkdir(exist_ok=True)
    names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT IN ('meta')")]
    for n in names:
        cols, rows = DB.query(con, f"SELECT * FROM {n}")
        with open(out / f"{n}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)
    print(f"Wrote {len(names)} CSV files to {out}")


def cmd_dashboard(a):
    from .dashboard import build
    path = build(DB.connect(), DB.WOD_HOME / "dashboard.html")
    print(f"Dashboard: {path}")
    if not a.no_open:
        import webbrowser
        webbrowser.open(path.resolve().as_uri())


def cmd_summary(a):
    """Compact, LLM-friendly text: paste it into any chatbot, or let an agent read it."""
    con = DB.connect()
    wid = _resolve(con, a.id)
    w = con.execute("SELECT * FROM workouts WHERE id = ?", (wid,)).fetchone()
    print(f"WORKOUT {wid} | {w['date']} | {w['name']} | format {w['format']} | score {w['score']}")
    print(f"elapsed {w['elapsed_s']}s moving {w['moving_s']}s between {w['between_s']}s ({w['between_pct']}%) notes: {w['notes'] or '-'}")
    print("round,pos,movement,amount,unit,counted(0=from the workout),expected,sets,duration_s,sec_per_rep,transition_after_s,flagged")
    for b in con.execute("SELECT * FROM blocks WHERE workout_id = ? ORDER BY seq", (wid,)):
        print(f"{b['round']},{b['pos_in_round']},{b['movement_name']},{b['reps']},{b['unit'] or 'reps'},{b['counted'] if b['counted'] is not None else 1},{b['expected']},{b['sets']},{b['duration_s']},"
              f"{b['sec_per_rep']},{b['transition_after_s']},{b['flagged']}")
    print("fresh_benchmarks (round 1): movement,time_for_10_s,estimated,reps_per_sec,first_time")
    for f in con.execute("SELECT m.name, f.* FROM fresh_benchmarks f JOIN movements m ON m.key=f.movement_key WHERE workout_id = ?", (wid,)):
        print(f"{f['name']},{f['time_for_10_s']},{f['estimated']},{f['reps_per_sec']},{f['first_time_seen']}")
    print("history (all workouts): movement,workouts,avg_reps_per_sec,best_fresh_10_s,biggest_unbroken_set")
    for m in con.execute("SELECT * FROM v_movement_summary"):
        print(f"{m['movement']},{m['workouts']},{m['avg_reps_per_sec']},{m['best_fresh_10_s']},{m['biggest_unbroken_set']}")


def cmd_doctor(a):
    ok = True
    def chk(name, good, fix=""):
        nonlocal ok
        ok &= bool(good)
        print(f"{'OK ' if good else 'MISSING'} {name}{'' if good else '  → ' + fix}")
    chk("Python " + sys.version.split()[0], sys.version_info >= (3, 9), "install Python 3.10-3.12")
    try:
        from . import ff
        chk("ffmpeg (" + ("system" if shutil.which("ffmpeg") else "bundled") + ")", ff.exe())
    except SystemExit:
        chk("ffmpeg", False, "run `wod setup`")
    for mod in ("mediapipe", "cv2", "numpy", "scipy", "pandas"):
        try:
            __import__(mod)
            chk(mod, True)
        except Exception as e:
            chk(mod, False, f"pip install -e . ({e.__class__.__name__})")
    chk("pose model", find_model(download=False) or a.download and find_model(), "run `wod doctor --download`")
    chk(f"data folder {DB.WOD_HOME}", DB.connect() is not None)
    print("\nReady." if ok else "\nFix the items above, then run `wod doctor` again.")


def cmd_setup(a):
    from .setup_cmd import setup
    setup(no_watcher=a.no_watcher)


def cmd_guide(a):
    from .setup_cmd import guide_text
    print(guide_text())


def cmd_watch(a):
    from .watch import watch
    watch(Path(a.inbox).expanduser() if a.inbox else DB.WOD_HOME / "inbox", once=a.once)


def main():
    # Windows terminals default to a legacy code page; reports use a few non-ASCII symbols
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="wod", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("analyze")
    s.add_argument("video")
    s.add_argument("--workout")
    s.add_argument("--date")
    s.add_argument("--hr")
    s.add_argument("--video-start")
    s.add_argument("--notes")
    s.add_argument("--force", action="store_true")
    s.add_argument("--workers", type=int, help="CPU cores for body tracking (default: all, up to 8)")
    s.add_argument("--fast", action="store_true", help="experimental: smaller body-tracking model, faster but less accurate")
    s.add_argument("--quiet", action="store_true", help="print only the final report (best for AI assistants)")
    s.add_argument("--fingerprint", help=argparse.SUPPRESS)   # when the video was pre-compressed elsewhere
    s = sub.add_parser("reanalyze")
    s.add_argument("id", nargs="?")
    s.add_argument("--all", action="store_true")
    sub.add_parser("rebuild")
    s = sub.add_parser("correct")
    s.add_argument("id")
    s.add_argument("--round", type=int)
    s.add_argument("--movement", required=True)
    s.add_argument("--reps", type=int, required=True)
    s.add_argument("--note")
    s = sub.add_parser("note")
    s.add_argument("id")
    s.add_argument("text")
    s = sub.add_parser("workout")
    s.add_argument("id", nargs="?", default="latest")
    sub.add_parser("list")
    sub.add_parser("stats")
    s = sub.add_parser("movement")
    s.add_argument("name")
    s = sub.add_parser("sql")
    s.add_argument("query")
    s.add_argument("--json", action="store_true")
    s.add_argument("--limit", type=int, default=200)
    sub.add_parser("schema")
    sub.add_parser("export")
    s = sub.add_parser("dashboard")
    s.add_argument("--no-open", action="store_true")
    s = sub.add_parser("parse")
    s.add_argument("text")
    s = sub.add_parser("summary")
    s.add_argument("id", nargs="?", default="latest")
    s = sub.add_parser("doctor")
    s.add_argument("--download", action="store_true")
    s = sub.add_parser("setup")
    s.add_argument("--no-watcher", action="store_true")
    sub.add_parser("guide")
    s = sub.add_parser("watch")
    s.add_argument("--inbox")
    s.add_argument("--once", action="store_true")
    a = ap.parse_args()
    if a.cmd == "parse":
        from .spec import parse_text
        print(json.dumps(parse_text(a.text.replace("\\n", "\n")), indent=1))
        return
    {"analyze": cmd_analyze, "reanalyze": cmd_reanalyze, "rebuild": cmd_rebuild, "correct": cmd_correct, "note": cmd_note,
     "workout": cmd_workout, "list": cmd_list, "stats": cmd_stats, "movement": cmd_movement, "sql": cmd_sql,
     "schema": cmd_schema, "export": cmd_export, "dashboard": cmd_dashboard, "summary": cmd_summary,
     "doctor": cmd_doctor, "watch": cmd_watch, "setup": cmd_setup, "guide": cmd_guide}[a.cmd](a)


if __name__ == "__main__":
    main()
