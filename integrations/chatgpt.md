# Using it with ChatGPT

The analysis runs on your computer. ChatGPT reads the results and answers your questions. Everything stays inside your normal ChatGPT plan: no API key.

## Codex (ChatGPT's coding agent: CLI, IDE extension or desktop app)
Codex signs in with your ChatGPT plan and reads this repo's `AGENTS.md` automatically.
1. Install the analyzer once (see the main README).
2. Open Codex in the repo folder (`cd automated-wod-analysis && codex`).
3. "Analyze ~/Downloads/IMG_1234.MOV" and paste the workout (or attach the screenshot).

The inbox watcher also uses `codex exec` to turn a workout screenshot into text if Claude Code isn't installed.

## ChatGPT chat (web, desktop or phone)
1. Analyze on your computer: `wod analyze ...`, or drop the video and a `.txt` of the workout into `~/WODs/inbox`.
2. Run `wod summary` and paste the output into ChatGPT, or upload `~/WODs/wod.db` (ChatGPT can query SQLite files) and ask, e.g. "How did my transitions change across rounds?"

## Custom GPT (optional)
Create a GPT with these instructions, then paste `wod summary` output or upload `wod.db` to it:

> You coach CrossFit athletes using data from the Automated WOD Analysis tool. Input is either `wod summary` text or a `wod.db` SQLite file (tables: workouts, blocks, sets, reps, movements, fresh_benchmarks; views: v_movement_summary, v_fatigue, v_transitions, v_round_trend, v_weekly_volume, v_repeats). Answer from the data only. Give a round table when asked about one workout, then 2-3 specific, actionable takeaways (largest transition costs, pace change between first and last rounds, fresh-speed comparisons). Note estimated values (fresh 10 from fewer than 10 reps), prescribed values (`counted = 0`: calories and distances come from the workout, only their time is measured) and that double-under counts are about ±10%.
