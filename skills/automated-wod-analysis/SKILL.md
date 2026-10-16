---
name: automated-wod-analysis
description: Analyze CrossFit/WOD workout videos into reps, splits, transitions, rest and fresh-speed benchmarks stored in a local database, and answer questions about past workouts. Use when someone sends a workout video or a workout screenshot, or asks about their training data.
---

# Automated WOD Analysis

Turns a filmed workout into: movements found, reps per set (e.g. 12+8), time per movement, transitions, rest, round times, score, and **fresh speed** (how long 10 reps take in round 1, before fatigue). Everything is saved in a local SQLite database (`~/WODs/wod.db`), so a video is never processed twice and the athlete can ask about their training over time.

The `wod` command does the heavy work on the user's own computer, for free: body tracking (MediaPipe) and rope-click audio. **You never watch the video frame by frame.** Your jobs: get the workout text, run `wod`, check flagged rounds, explain the results, answer questions from the database. That keeps every run inside the user's normal plan limits; no API keys are involved.

## 0. Check the setup
Run `wod doctor`. If `wod` isn't found, the user needs to install it once from https://github.com/growthenginenowoslawski/automated-wod-analysis (Mac: `bash install/mac.sh`, Windows: `powershell -ExecutionPolicy Bypass -File install\windows.ps1`). Say so plainly and stop until it's installed. If `doctor` lists something missing, give its fix line.

## 1. Get the workout text (required)
Knowing the movements, order and reps is what makes counting accurate. From a screenshot, write plain lines and ignore notes, scaling and links:
```
4 Rounds
1 Muscle Up
25ft Sandbag Carry 150/100lbs
12/10 Calorie C2 Bike
Rest 2:00
```
Understood: `AMRAP 8:00`, `N Rounds (For Time)`, `21-15-9`, time caps, `Rest 2:00`, `12/10` (first number is used), distances (`25ft`, `200m`) and calories. Check with `wod parse "<lines joined with \n>"`; a movement with `"key": null` isn't in the library yet and won't be tracked. Tell the user which ones.

## 2. Run it
`wod analyze <video> --workout "<lines joined with \n>" [--date YYYY-MM-DD] [--notes "..."]`
- A video analyzed before is recognized by its fingerprint and its saved report comes back instantly. Don't add `--force` unless asked.
- Sideways phone video is rotated automatically. Long videos use every CPU core. Expect roughly 1-3 minutes of processing per 10 minutes of video on a recent laptop. Run it in the background and poll if your tool has a time limit.
- Workouts where a movement repeats inside a round, timed movements (bike, row, ski, carries) or prescribed rest run in **sequence mode**: blocks are matched to the written order, and a step that can't be found is reported as missing instead of shifting everything after it.

## 3. Check flags, not the whole video
Under **Needs a look**, each flagged round lists a time window and 4 review frames (`~/WODs/archive/<id>/review/`). Look at those frames only, with a model that is good at images (small/fast models misread movement). If the count was wrong, save the fix:
`wod correct <id> --round N --movement "<name>" --reps N --note "..."`
Corrections survive every re-analysis and become test cases (`python -m tests.check_accuracy`).

## 4. Reply
Give the round table from the report and 2-3 takeaways the athlete can act on next time, e.g. which transition cost the most, whether reps or transitions slowed in later rounds, and how fresh speed compares with their best. Mention **Fresh speed** lines (a new movement sets a baseline) and **You've done this workout before** when present. Offer `wod dashboard` (opens a local page, no account).

## 5. Answer questions about their training
Use the database, not memory:
- `wod stats` · `wod movement "<name>"` · `wod list` · `wod workout <id|latest>` · `wod summary [id]`
- `wod sql "SELECT ..."` (read-only; add `--json` for machine-readable) · `wod schema`

Tables: `workouts` (date, name, format, score, rounds_complete, total_reps, elapsed_s, moving_s, between_s, between_pct, rest_s, notes), `blocks` (one movement in one round: pos_in_round, label, start_s, end_s, duration_s, reps, expected, unit, counted, sets like "12+8", sec_per_rep, reps_per_sec, transition_after_s, next_movement, flagged, corrected, load), `sets`, `reps` (every rep's timestamp), `movements` (first_seen_date), `fresh_benchmarks` (time_for_10_s, estimated, reps_per_sec, unit, first_time_seen), `corrections`.
Views: `v_movement_summary`, `v_fatigue`, `v_transitions`, `v_round_trend`, `v_weekly_volume`, `v_repeats`.
Say when a number is estimated (fresh 10 from fewer than 10 reps), prescribed rather than counted (`counted = 0`: bike calories and carry distances are taken from the workout, only their time is measured), and that double-under counts are about ±10%.

## If the video is on another computer
If you can only reach the user's computer through a remote shell with short time limits: compress there in ~2-minute chunks (`ffmpeg -ss S -t 125 -i VIDEO -vf "scale=-2:720,fps=15" -an -c:v libx264 -preset ultrafast -crf 28 part_S.mp4`, a few at a time with `&` and `wait`), extract audio (`-vn -ac 1 -ar 16000 -c:a aac -b:a 48k audio.m4a`), transfer the parts (retry a failed one once), join them with `ffmpeg -f concat`, add the audio back, and run `wod analyze joined.mp4 --fingerprint <fingerprint of the original>` where you can run Python. Prefer running locally whenever possible.

## Filming checklist (share when a video is hard to read)
Phone propped and still; whole body plus bar, rope area and machines in frame; side-on or 45°; start recording before "3-2-1-go" with the timer audible; one athlete in frame.
