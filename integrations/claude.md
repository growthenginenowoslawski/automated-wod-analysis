# Using it with Claude

The analysis runs on your computer. Claude reads the results, checks flagged rounds and answers your questions. Everything stays inside your normal Claude plan: no API key.

## Claude Code (Mac or Windows)
1. Install the analyzer once (see the main README).
2. Add the skill:
   - Mac: `cp -R skills/automated-wod-analysis ~/.claude/skills/`
   - Windows: `xcopy /E /I skills\automated-wod-analysis %USERPROFILE%\.claude\skills\automated-wod-analysis`
3. In Claude Code: "Analyze ~/Downloads/IMG_1234.MOV" and paste or attach a screenshot of the workout.

## Claude desktop app
Claude needs to be able to run commands on your computer (Claude Code inside the desktop app, or a chat linked to your computer). Add it as a custom skill by uploading `automated-wod-analysis-skill.zip` from the latest GitHub release (or zip the `skills/automated-wod-analysis` folder yourself) in the app's skills settings, then ask the same way.

## Claude on the web or phone (no access to your computer)
Run the analysis yourself (`wod analyze ...` or drop the video in `~/WODs/inbox`), then paste the output of `wod summary` into the chat and ask your question.
