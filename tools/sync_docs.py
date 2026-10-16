"""Regenerate the assistant instruction files from the single source: wod/agent_guide.md.
Run after editing the guide:  python tools/sync_docs.py"""
from pathlib import Path
import sys
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from wod.setup_cmd import guide_text, skill_text
(root / "skills/automated-wod-analysis").mkdir(parents=True, exist_ok=True)
(root / "skills/automated-wod-analysis/SKILL.md").write_text(skill_text(), encoding="utf-8")
dev = ("\n\n## Working on this repository\n`pip install -e \".[dev]\"`, then `pytest`. After changing counting rules run "
       "`wod reanalyze --all` and `python -m tests.check_accuracy`. Edit `wod/agent_guide.md`, then `python tools/sync_docs.py` "
       "to regenerate SKILL.md, AGENTS.md and CLAUDE.md.\n")
(root / "AGENTS.md").write_text(guide_text() + dev, encoding="utf-8")
(root / "CLAUDE.md").write_text("Follow AGENTS.md in this folder (the same instructions for every AI assistant).\n\n@AGENTS.md\n", encoding="utf-8")
print("synced")
