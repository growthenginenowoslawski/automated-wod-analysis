# Automated WOD Analysis: instructions for AI assistants

You are helping someone analyze a filmed CrossFit workout. **Assume they are not technical: do every step yourself.** Only ask them for things you cannot do: picking the video, telling you the workout (or sending a screenshot), or clicking "Allow" if their computer asks.

What they get: movements found, reps per set (e.g. 12+8), time for each movement in each round, transitions, rest, round times, score, and **fresh speed** (how long 10 reps take in round 1, before fatigue). Everything is saved on their computer in `~/WODs/` so a video is never processed twice and they can ask questions later.

The `wod` program does the heavy work on their computer for free (body tracking + audio). **Never look at the video frame by frame**: that wastes their usage limit. You run commands, read short text reports, and only look at a few saved frames when a round is flagged.

## 1. Make sure it's installed

Run `wod doctor`. If it prints "Ready", go to step 2.

If `wod` is not found, install it. These need no password, no admin rights and no other software:

**Mac or Linux** (run in the terminal; takes 2-5 minutes):
```
curl -LsSf https://astral.sh/uv/install.sh | sh
~/.local/bin/uv tool install --python 3.12 "automated-wod-analysis @ https://github.com/growthenginenowoslawski/automated-wod-analysis/archive/refs/heads/main.zip"
~/.local/bin/wod setup
```

**Windows** (run in PowerShell; takes 2-5 minutes):
```
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
& "$HOME\.local\bin\uv.exe" tool install --python 3.12 "automated-wod-analysis @ https://github.com/growthenginenowoslawski/automated-wod-analysis/archive/refs/heads/main.zip"
& "$HOME\.local\bin\wod.exe" setup
```

`wod setup` downloads the body-tracking model, creates `~/WODs/`, installs these instructions for Claude and Codex, and starts an inbox folder watcher. If `wod` still isn't found afterwards, use the full path (`~/.local/bin/wod`, or `$HOME\.local\bin\wod.exe` on Windows) for the rest of this conversation, and tell the user that new terminal windows will find it.

To update later: `uv tool upgrade automated-wod-analysis`.

## 2. Get the video and the workout

- **The video**: ask where it is if they didn't say (usually Downloads, or AirDropped from their phone). Use the full path. Find it yourself if you can, e.g. the newest `.MOV`/`.mp4` in Downloads, and confirm the file name with them.
- **The workout (required)**: knowing the movements, order and reps is what makes counting accurate. If they send a screenshot, read it and write plain lines. Leave out coach's notes, scaling and links:
```
4 Rounds
1 Muscle Up
25ft Sandbag Carry 150/100lbs
12/10 Calorie C2 Bike
Rest 2:00
```
Understood: `AMRAP 8:00`, `N Rounds (For Time)`, `21-15-9`, time caps, `Rest 2:00`, `12/10` (the first number is used), distances (`25ft`, `200m`) and calories. Check it with `wod parse "<lines joined with \n>"`. Any movement showing `"key": null` isn't supported yet and will be skipped: tell them which.

## 3. Run it

```
wod analyze "<video path>" --workout "<lines joined with \n>" --quiet
```
- Add `--date YYYY-MM-DD` if the video isn't from today, and `--notes "..."` for anything they mention (sleep, scaling, how it felt).
- It takes roughly 2-5 minutes per 10 minutes of video, depending on the computer (it uses every CPU core). If your tool has a time limit, run it in the background and check back.
- A video that was analyzed before is recognized, and its saved report comes back instantly. Don't use `--force` unless they ask.
- Only if it's far too slow on an old computer: `--fast` uses a smaller tracking model (experimental, less accurate). Say so in your summary if you used it.

## 4. Check flagged rounds only

Under **Needs a look**, each flagged step lists a time window and saved frames (`~/WODs/archive/<workout id>/review/`). Look at those few frames only; don't use a small/fast model for this, they misread movement. If a count was wrong, save the fix:
```
wod correct <workout id> --round N --movement "<name>" --reps N --note "..."
```
Fixes are kept forever and re-applied whenever the analysis improves. Steps marked "count not visible" were hidden from the camera. Looking at frames won't help; suggest a better camera angle next time.

## 5. Explain it

Show the round table from the report, then give 2-3 specific things they can act on next time:
- which transition cost the most time
- whether reps or transitions slowed down in later rounds
- machine pace (cal/min) dropping after round 1
- how fresh speed compares with their best (the first time a movement appears, it sets their baseline)

Mention "You've done this workout before" when it appears. Be clear about what was measured and what was taken from the workout: bike calories and carry distances come from the whiteboard, only their time is measured. Double-under counts are about ±10%. Offer `wod dashboard`, which opens charts in their browser.

## 6. Answer questions about their training

Use their database, never memory or guesses:
- `wod stats`: every movement's fresh-10 time, average pace, biggest unbroken set, slowest transitions
- `wod movement "<name>"` · `wod list` · `wod workout <id|latest>` · `wod summary`
- `wod sql "SELECT ..."` (read-only; `--json` for machine-readable) · `wod schema` for the tables

Tables: `workouts` (date, name, format, score, rounds_complete, total_reps, elapsed_s, moving_s, between_s, between_pct, rest_s, notes), `blocks` (one movement in one round: pos_in_round, label, start_s, end_s, duration_s, reps, expected, unit (reps/cal/ft/m), counted (0 = taken from the workout), sets like "12+8", sec_per_rep, reps_per_sec, transition_after_s, next_movement, flagged, corrected, load), `sets`, `reps` (every rep's timestamp), `movements`, `fresh_benchmarks` (time_for_10_s, estimated, reps_per_sec, unit, first_time_seen), `corrections`. Views: `v_movement_summary`, `v_fatigue`, `v_transitions`, `v_round_trend`, `v_weekly_volume`, `v_repeats`.

## Keeping it cheap

- Each workout is best done in a **new chat**: long chats re-send their whole history on every step.
- For a routine analysis, a mid-size model (e.g. Sonnet, or ChatGPT's default) is plenty. Save the largest model for adding movements or debugging.
- Hands-off option: they can drop the video and a `.txt` of the workout (same name) into `~/WODs/inbox`. It is analyzed automatically, using no AI at all, and they can ask you questions afterwards.

## If something goes wrong

- Run `wod doctor` and follow its fix lines.
- "Pose model" missing: `wod doctor --download`.
- The video is somewhere you can't reach: ask them to move it to Downloads.
- Wrong results with a partner in frame, or the rig blocking the view: share the filming tips: phone propped and still; whole body, bar, rope area and machines in frame; side-on or 45° so the rig doesn't hide them; start recording before "3-2-1-go"; partners out of shot.


## Working on this repository
`pip install -e ".[dev]"`, then `pytest`. After changing counting rules run `wod reanalyze --all` and `python -m tests.check_accuracy`. Edit `wod/agent_guide.md`, then `python tools/sync_docs.py` to regenerate SKILL.md, AGENTS.md and CLAUDE.md.
