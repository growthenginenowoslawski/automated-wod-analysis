"""Database round-trip on a synthetic analysis (no video or model needed)."""
import json

from wod import db as DB


def _block(name, key, start, reps, gap, expected, unit="reps", counted=True):
    times = [round(start + 1 + i * gap, 2) for i in range(reps)] if counted else []
    end = (times[-1] + 0.5) if times else start + 30
    return {"movement": name, "key": key, "start": start, "end": end, "duration": round(end - start, 1), "work": round(end - start, 1),
            "reps": reps, "expected": expected, "sets": [reps], "breaks": [], "sec_per_rep": round((end - start) / reps, 2),
            "transition_after": 5.0, "unit": unit, "counted": counted, "load": None,
            "set_details": [{"start": start, "end": end, "reps": reps if counted else 0, "rep_times": times}]}


def _result():
    r1 = [_block("Toes to Bar", "toes_to_bar", 0, 6, 1.6, 6), _block("C2 Bike", "bike", 20, 12, 0, 12, "cal", False)]
    r2 = [_block("Toes to Bar", "toes_to_bar", 60, 6, 1.8, 6), _block("C2 Bike", "bike", 80, 12, 0, 12, "cal", False)]
    r1[-1]["transition_after"] = r2[-1]["transition_after"] = None
    rounds = [{"round": 1, "start": 0, "end": 50, "complete": True, "duration": 50, "blocks": r1},
              {"round": 2, "start": 60, "end": 110, "complete": True, "duration": 50, "blocks": r2}]
    spec = {"name": "Test", "format": "rounds", "rounds": 2,
            "movements": [{"name": "Toes to Bar", "key": "toes_to_bar", "reps": 6},
                          {"name": "C2 Bike", "key": "bike", "reps": 12, "unit": "cal"}]}
    totals = {"start": 0, "end": 110, "elapsed": 110, "moving": 100, "between": 10, "between_pct": 9, "rounds_complete": 2,
              "extra_reps": 0, "score": "2 rounds"}
    return {"spec": spec, "rounds": rounds, "totals": totals, "flags": [], "per_movement": {}, "observed_order": []}


def test_store_and_views(tmp_path):
    con = DB.connect(tmp_path)
    res = json.loads(json.dumps(_result()))
    DB.store(con, "2026-01-01_test", res, {"video_name": "t.mov", "video_fp": "abc"}, tmp_path, "2026-01-01")
    assert con.execute("SELECT COUNT(*) FROM blocks").fetchone()[0] == 4
    assert con.execute("SELECT COUNT(*) FROM reps").fetchone()[0] == 12
    f = {r["movement_key"]: dict(r) for r in con.execute("SELECT * FROM fresh_benchmarks")}
    assert f["toes_to_bar"]["estimated"] == 1 and 14 < f["toes_to_bar"]["time_for_10_s"] < 18
    assert f["bike"]["unit"] == "cal" and f["bike"]["time_for_10_s"] > 0
    s = {r["movement_key"]: dict(r) for r in con.execute("SELECT * FROM v_movement_summary")}
    assert s["toes_to_bar"]["total_reps"] == 12 and s["toes_to_bar"]["biggest_unbroken_set"] == 6
    assert con.execute("SELECT COUNT(*) FROM v_fatigue").fetchone()[0] == 2
    assert DB.find_by_fp(con, "abc")["id"] == "2026-01-01_test"


def test_corrections_apply(tmp_path):
    con = DB.connect(tmp_path)
    DB.add_correction(con, "w1", 2, "toes_to_bar", "reps", 5)
    res = DB.apply_corrections(con, "w1", json.loads(json.dumps(_result())))
    assert res["rounds"][1]["blocks"][0]["reps"] == 5 and res["rounds"][1]["blocks"][0]["corrected"]
    assert res["rounds"][0]["blocks"][0]["reps"] == 6
