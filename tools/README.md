# Checking browser tracking against the desktop tool

1. Convert a video the desktop tool already analyzed (its `.work/<id>/small.mp4`) to VP9 webm:
   `ffmpeg -i small.mp4 -an -c:v libvpx-vp9 -crf 14 -b:v 0 -g 15 -deadline realtime -cpu-used 8 -row-mt 1 v.webm`
2. Serve this folder (`python3 -m http.server 8080`) and run `node tools/run_video.mjs v.webm out.json`
   (needs `playwright-core`; tracks at 15 fps on the CPU, same model and settings as the desktop tool).
3. `python tools/compare.py IMG_2787 out.json` compares landmarks and runs the counting engine on both.

Results on 2026-10-17 (headless Chromium, CPU):

| Video | Python body found | Browser body found | Engine checks on browser data |
| --- | --- | --- | --- |
| IMG_2787 (AMRAP, one athlete) | 96.4% | 96.4% | all pass; moving time 225 vs 227 s |
| IMG_2803 (intervals, partner in frame) | 78.9% | 84.4% | all pass; browser follows the partner on the bike at times (rest vs transition split differs ~70 s) |
