# Your workout database

`~/WODs/wod.db` is a standard SQLite file. Any SQLite tool, `wod sql "..."`, Claude, Codex or ChatGPT (upload the file) can read it. `wod schema` prints the exact definitions.

## Tables

| Table | One row per | Key columns |
|---|---|---|
| `workouts` | analyzed video | date, name, format (amrap / for_time / rounds), spec_json, spec_hash (same workout ⇒ same hash), score, rounds_complete, total_reps, elapsed_s, moving_s, between_s, between_pct, rest_s, notes, video_fp |
| `blocks` | movement in a round | round, pos_in_round, label, movement_key, start_s, end_s, duration_s, reps, expected, unit (reps/cal/ft/m), counted (0 = taken from the workout), sets ("12+8"), breaks_json, sec_per_rep, reps_per_sec, transition_after_s, next_movement, flagged, corrected, load |
| `sets` | unbroken set | block_id, set_idx, start_s, end_s, reps |
| `reps` | single rep | t_s (seconds into the video), since_prev_s |
| `movements` | movement ever seen | first_seen_date, first_seen_workout |
| `fresh_benchmarks` | movement × workout | time_for_10_s (round 1), estimated, reps_per_sec, unit, first_time_seen |
| `corrections` | fix you made | round, movement_key, value, note |

## Views (ready-made answers)

- `v_movement_summary`: per movement: total, average pace, best/latest/average fresh-10, biggest unbroken set
- `v_fatigue`: pace in round 1 vs the last full round, per workout and movement
- `v_transitions`: from → to: count, average, best, worst
- `v_round_trend`: round times, moving time and transition time per round
- `v_weekly_volume`: reps and minutes per movement per week
- `v_repeats`: workouts you've done more than once, side by side

## Examples

```sql
-- How much time did transitions cost per workout?
SELECT date, name, ROUND(between_s) AS seconds_between, between_pct FROM workouts ORDER BY date;

-- Toes-to-bar pace over time
SELECT w.date, ROUND(AVG(b.sec_per_rep), 2) AS sec_per_rep FROM blocks b JOIN workouts w ON w.id = b.workout_id
WHERE b.movement_key = 'toes_to_bar' GROUP BY w.date ORDER BY w.date;

-- Every double-under set that broke
SELECT workout_id, round, sets FROM blocks WHERE movement_key = 'double_under' AND n_sets > 1;
```

## The archive

`~/WODs/archive/<workout>/` keeps the body points for every frame (`pose.json.gz`), the audio, the workout, the analysis and the report. `wod reanalyze --all` and `wod rebuild` work from these, so you can delete the original videos.
