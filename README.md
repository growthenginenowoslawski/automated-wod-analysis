# Automated WOD Analysis

Film your CrossFit workout, and get back:

- the **movements**, **reps per set** (12 + 8), and **time for every movement, every round**
- **transitions and rest**: where the clock actually went
- **round times, your score**, and how your pace changed from the first round to the last
- **fresh speed**: how long 10 reps of each movement take in round 1, before fatigue, tracked over time
- a **local database** of every workout, round, set and rep, so you can ask "how has my snatch pace changed?" without reprocessing anything

It runs **on your own computer** (Mac or Windows). The video never leaves it. Use it with **Claude** or **ChatGPT**: your assistant reads the results and answers questions, inside your normal plan limits. No API keys, no extra accounts.

```
| Step              | Round 1                     | Round 2                     | Round 3                      |
|-------------------|-----------------------------|-----------------------------|------------------------------|
| 12 cal C2 Bike    | 46s · 16 cal/min · then 20s | 60s · 12 cal/min · then 9s  | 47s · 15 cal/min · then 32s  |
| 18 cal C2 Bike    | 56s · 19 cal/min · then 35s | 79s · 14 cal/min · then 7s  | 104s · 10 cal/min · then 11s |
| 24 cal C2 Bike    | 87s · 17 cal/min · then 16s | 131s · 11 cal/min · then 6s | 127s · 11 cal/min            |
```

## Install (once)

You need about 1 GB of free space. The installer sets up ffmpeg, Python 3.12 if missing, the analyzer, a 9 MB body-tracking model and an inbox folder.

**Mac.** Open Terminal:
```bash
git clone https://github.com/growthenginenowoslawski/automated-wod-analysis.git
cd automated-wod-analysis
bash install/mac.sh
```

**Windows 10/11.** Open PowerShell:
```powershell
git clone https://github.com/growthenginenowoslawski/automated-wod-analysis.git
cd automated-wod-analysis
powershell -ExecutionPolicy Bypass -File install\windows.ps1
```
No git? Download the ZIP from the green **Code** button, unzip it and run the same install line inside the folder.

Check it any time with `wod doctor`.

## Use it

**With Claude** (Claude Code or the Claude desktop app). Add the skill (see [integrations/claude.md](integrations/claude.md)), then say *"Analyze ~/Downloads/IMG_1234.MOV"* and attach a screenshot of the workout.

**With ChatGPT** (Codex, or plain ChatGPT chat). See [integrations/chatgpt.md](integrations/chatgpt.md). Codex reads this repo's `AGENTS.md` automatically. In regular ChatGPT, paste the output of `wod summary` or upload `~/WODs/wod.db`.

**On its own.**
```bash
wod analyze ~/Downloads/IMG_1234.MOV --workout "AMRAP 8:00\n36 Double Unders\n6 Toes to Bar\n6 Power Snatch 95/65lbs"
```
or drop the video and a `.txt` with the workout (same name) into `~/WODs/inbox`. With Claude Code or Codex installed, a screenshot works instead of the `.txt`.

## Ask your data

```bash
wod stats                       # every movement: fresh-10 time, average pace, biggest unbroken set, slowest transitions
wod movement "toes to bar"      # one movement's history, round by round
wod workout latest              # a report again, instantly
wod summary                     # compact text for any chatbot
wod dashboard                   # charts in your browser (offline)
wod sql "SELECT * FROM v_weekly_volume"
```

Everything lives in `~/WODs/`: `wod.db` (SQLite), `archive/` (the raw tracking data for every workout, about 5-10 MB each), `dashboard.html`. The same video is recognized and never processed twice. When the counting rules improve, `wod reanalyze --all` updates every past workout in seconds, without the videos. Wrong count? `wod correct latest --round 2 --movement "double unders" --reps 36`. Your fix sticks and becomes a test case. See [docs/database.md](docs/database.md).

## What it can track

| Movement | How | Confidence |
|---|---|---|
| Double-unders, singles | hip-bounce rhythm, cross-checked with the rope's clicks in the audio | time: high · count: ±10% |
| Toes-to-bar, knees-to-elbows | hanging, feet rising | high |
| Power snatch, clean & jerk, thrusters, push press/jerk, shoulder-to-overhead | bar overhead (lockouts) | high |
| Bike, row, ski erg | staying in place with legs cycling | time: high (calories come from the workout) |
| Sandbag/farmer/front-rack carries | travel with the load in front | time: medium (distance comes from the workout) |
| Muscle-ups | hanging and getting above the rings/bar | time: medium · count only when clearly visible |
| Pull-ups, chest-to-bar, power cleans | hanging + pull · bar to shoulders | medium (less tested) |

Anything else in a workout is listed as "not in the movement library yet" and skipped. Adding one is a small change in `wod/movements.py`. Pull requests are welcome, especially with a labeled video.

## Film it so it can be read

1. **Prop the phone up** and don't touch it until you're done. Landscape is best.
2. **Get everything in frame**: your whole body, the bar, rope area, rig and machines.
3. **Make sure the rig doesn't block you.** Film from the side so you're visible above the rings or bar.
4. **Keep training partners out of the shot.** The tracker follows one person.
5. **Start recording before "3-2-1-go"**, with the timer beep audible.

More in [docs/filming.md](docs/filming.md).

## How it works

1. `ffmpeg` straightens sideways phone video and shrinks it.
2. Google's MediaPipe pose model finds 33 body points in every frame. This uses all your CPU cores, about 1-3 minutes per 10 minutes of video.
3. Body signals (wrist height, hip bounce, feet off the floor, hips staying put…) and audio clicks become events. The workout text says which movements, in what order and how many, so the analyzer only has to find and count known things.
4. Workouts with repeated steps, machines, carries or prescribed rest use **sequence mode**. It anchors on the most reliable movement (e.g. the bike) and fills the steps between.
5. Results are checked against the workout. Rounds that don't add up are flagged with 4 saved frames, so your assistant looks at a few pictures instead of the whole video. This is what keeps it cheap enough to run inside a normal Claude or ChatGPT plan.

## Development

```bash
pip install -e ".[dev]"
pytest                          # parser + database tests (no video needed)
python -m tests.check_accuracy  # re-counts your labeled workouts + every correction you've saved
```

## License

MIT. Not affiliated with CrossFit, LLC.
