"""PreToolUse guard for Read, Grep and Glob, scoped to engineering subagents.

Blocks (exit 2) a call whose file_path, path, pattern or glob points into
registry/predictions/, so agents that write prompts, filters or redaction
never see the predictions they will be scored against. With ``--also-prompts``
(the corpus-engineer's hook) it also blocks registry/prompts/.

Best effort: a Grep or Glob rooted at the project directory still searches
the predictions folder. That gap matters from milestone M8, when predictions
exist; it is recorded in the harness spec.
Fails closed: any internal error blocks the call.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

NEEDLE = "registry/predictions"
PROMPTS = "registry/prompts"


def main() -> None:
    needles = [NEEDLE] + ([PROMPTS] if "--also-prompts" in sys.argv[1:] else [])
    event = c.read_event()
    root = c.project_root(event)
    tool_input = event.get("tool_input") or {}
    for field in ("file_path", "path", "pattern", "glob"):
        value = tool_input.get(field)
        if not isinstance(value, str) or not value:
            continue
        key = c.rel_key(value, root) if field in ("file_path", "path") else value.replace("\\", "/").casefold()
        for needle in needles:
            if key and needle in key:
                c.block(
                    f"Viveka: blocked access to {needle}/. This agent must not see the predictions it will be "
                    "scored against, and the corpus engineer must not see coding prompts."
                )


if __name__ == "__main__":
    c.run_guard(main)
