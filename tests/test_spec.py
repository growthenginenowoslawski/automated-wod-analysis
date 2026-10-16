from wod.spec import parse_text


def test_amrap():
    s = parse_text("Conditioning 1 (Metcon)\nAMRAP 8:00\n36 Double Unders\n6 Toes to Bar\n6 Power Snatch 95/65lbs*")
    assert s["format"] == "amrap" and s["time_cap_s"] == 480
    assert [m["key"] for m in s["movements"]] == ["double_under", "toes_to_bar", "power_snatch"]
    assert s["movements"][2]["load"] == "95/65lbs"


def test_intervals_with_units_rest_and_notes():
    s = parse_text("4 Rounds\n1 Muscle Up\n25ft Sandbag Carry 150/100lbs\n12/10 Calorie C2 Bike\nRest 2:00\n\n"
                   "Athlete Notes: Bike at a pace\nDuration: Long\nScaling\n- Muscle Up: anything")
    assert s["format"] == "rounds" and s["rounds"] == 4 and s["rest_s"] == 120
    mv = s["movements"]
    assert [m["key"] for m in mv] == ["muscle_up", "carry", "bike"]
    assert mv[1]["unit"] == "ft" and mv[1]["reps"] == 25
    assert mv[2]["unit"] == "cal" and mv[2]["reps"] == 12 and mv[2]["reps_alt"] == "10"


def test_rep_scheme():
    s = parse_text("21-15-9\nThrusters 95 lb\nPull-ups")
    assert s["rep_scheme"] == [21, 15, 9] and s["rounds"] == 3
    assert [m["key"] for m in s["movements"]] == ["thruster", "pull_up"]


def test_rounds_for_time():
    s = parse_text("5 Rounds For Time\n10 Thrusters 95 lb\n15 Pull-ups")
    assert s["format"] == "rounds" and s["rounds"] == 5
