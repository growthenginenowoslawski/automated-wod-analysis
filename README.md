# Automated WOD Analysis

**Film your CrossFit workout. Get back exactly where your time went.**

- every movement, **reps per set** (12 + 8) and **time per movement, per round**
- **transitions and rest**: the seconds you lose between movements
- **round times, your score**, and how your pace changed from the first round to the last
- **fresh speed**: how fast you do 10 reps in round 1, before fatigue, tracked over time
- a private **workout history** on your own computer you can ask questions about ("how has my bike pace changed?")

Works on **Mac and Windows**, with **Claude** or **ChatGPT**. Your video never leaves your computer, and it runs inside your normal Claude/ChatGPT plan: no API keys, no extra accounts.

---

## Get started: paste one message

Open **Claude Code** (in the Claude desktop app) or **Codex** (ChatGPT's agent app). Choose a folder if it asks, any folder is fine. Then paste this:

> Set up Automated WOD Analysis for me by following the instructions at https://raw.githubusercontent.com/growthenginenowoslawski/automated-wod-analysis/main/AGENTS.md. Do every step yourself. I'm not technical, so only ask me when you need me to do something. Then analyze my workout video.

Your assistant installs everything, which takes a few minutes and needs no password. Then it asks you for:
1. **the video**, e.g. "it's the newest video in my Downloads"
2. **the workout**: paste the whiteboard text or attach a screenshot

That's it. Next time just say *"Analyze my workout video"*. It remembers how.

> **Tip:** start a new chat for each workout. It keeps your usage low.

---

## What you get

```
| Step              | Round 1                     | Round 2                     | Round 3                      |
|-------------------|-----------------------------|-----------------------------|------------------------------|
| 12 cal C2 Bike    | 46s · 16 cal/min · then 20s | 60s · 12 cal/min · then 9s  | 47s · 15 cal/min · then 32s  |
| 18 cal C2 Bike    | 56s · 19 cal/min · then 35s | 79s · 14 cal/min · then 7s  | 104s · 10 cal/min · then 11s |
| 24 cal C2 Bike    | 87s · 17 cal/min · then 16s | 131s · 11 cal/min · then 6s | 127s · 11 cal/min            |
```
Plus your longest transitions, fresh-speed baselines, anything worth a second look, and a dashboard with charts across all your workouts.

## How to film

1. **Prop your phone up** and don't touch it until you're done.
2. **Fit everything in the shot**: your whole body, the barbell, the rig, the rope area and the machines.
3. **Film from the side or at an angle**, so the rig doesn't block you on the bar or rings.
4. **Keep training partners out of the shot.** It follows one person.
5. **Hit record before "3-2-1-go".**

## No AI needed for the analysis itself

After setup, drop a video and a `.txt` with the workout (same file name) into the **WODs → inbox** folder in your home folder. It's analyzed automatically and you get a notification. Then ask your assistant questions whenever you like.

## What it can track

| Movement | Confidence |
|---|---|
| Double-unders, single-unders | time: high · count: ±10% |
| Toes-to-bar, knees-to-elbows | high |
| Snatches, clean & jerks, thrusters, push press/jerk, shoulder-to-overhead | high |
| Bike, row, ski erg | time: high (calories come from the workout) |
| Sandbag / farmer / front-rack carries | time: medium (distance comes from the workout) |
| Muscle-ups | time: medium · count only when clearly visible |
| Pull-ups, chest-to-bar, power cleans | medium |

Anything else in a workout is skipped, and the report tells you which. Adding a movement is a small change. Contributions are welcome.

---

## For the technically curious

<details>
<summary>Manual install, commands, how it works</summary>

**Install without an assistant.** Mac/Linux terminal:
```bash
curl -LsSf https://raw.githubusercontent.com/growthenginenowoslawski/automated-wod-analysis/main/install/mac.sh | bash
```
Windows PowerShell:
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/growthenginenowoslawski/automated-wod-analysis/main/install/windows.ps1 | iex"
```
Both use [uv](https://docs.astral.sh/uv/), which brings its own Python. ffmpeg comes bundled. Nothing needs admin rights.

**Commands.**
```
wod analyze VIDEO --workout "AMRAP 8:00\n36 Double Unders\n6 Toes to Bar"   # --fast, --quiet, --notes, --date
wod stats | wod movement "toes to bar" | wod list | wod workout latest | wod summary
wod dashboard                   # charts in your browser, offline
wod sql "SELECT * FROM v_weekly_volume"     # read-only SQL; `wod schema` lists tables
wod correct latest --round 2 --movement "double unders" --reps 36
wod reanalyze --all             # re-count every past workout from saved data (no videos needed)
wod guide                       # the instructions AI assistants follow
wod doctor | wod setup | wod watch
```

**Plain chat (no agent).** Run `wod summary` and paste the output into Claude or ChatGPT, or upload `~/WODs/wod.db`; both can read SQLite files.

**Where your data lives.** `~/WODs/wod.db` (SQLite), `~/WODs/archive/` (tracking data per workout, about 5-10 MB each), `~/WODs/dashboard.html`. See [docs/database.md](docs/database.md).

**How it works.**
1. The video is straightened and shrunk.
2. Google's MediaPipe pose model finds 33 body points per frame, using all CPU cores. That's about 5 minutes for a 24-minute video on a 2-core machine, and faster on a modern laptop.
3. Body signals and the rope's clicks in the audio become events.
4. The workout text tells it what to look for, in what order.
5. Counts are checked against the workout, and anything that doesn't add up is flagged with 4 saved frames for the assistant to check.

The assistant reads text, never the video.

**Develop.** `pip install -e ".[dev]"`, `pytest`, `python -m tests.check_accuracy`. Assistant instructions live in `wod/agent_guide.md`; run `python tools/sync_docs.py` after editing.
</details>

MIT license. Not affiliated with CrossFit, LLC.
