"""PreToolUse guard for Bash and PowerShell commands.

Best effort, not a security boundary: permission rules in .claude/settings.json
are the first line, and the registry hash manifest is the real record. Blocks
(exit 2) a command that

* mentions a protected path (a frozen registry file, the frozen manifest, the
  change ledger, data/raw/ or runs/) together with a write, move or delete
  verb or an output redirect; or
* calls the Anthropic API directly (api.anthropic.com, or inline
  `import anthropic` / `from anthropic`) outside `uv run viveka`, because
  coders run only inside pipeline stages (principle H1).

Fails closed: any internal error blocks the command.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

# Redirects to nowhere are harmless; strip them before looking for writes.
_HARMLESS_REDIRECTS = re.compile(r"\d?>\s*(\$null|/dev/null|nul)\b|\d?>&\d")

_WRITE_PATTERNS = [
    r"(?<![-=<])>",  # a redirect; "->", "=>" and "<>" in text are not
    r"\brm\b", r"\brmdir\b", r"\bdel\b", r"\berase\b", r"\bunlink\b", r"\btruncate\b",
    r"\bmv\b", r"\bmove\b", r"\bcp\b", r"\bcopy\b", r"\btee\b", r"\bsed\b[^|;&]*\s-i",
    r"\bremove-item\b", r"\bri\b", r"\bmove-item\b", r"\bmi\b", r"\bcopy-item\b", r"\bcpi\b",
    r"\brename-item\b", r"\bren\b", r"\bset-content\b", r"\bsc\b", r"\badd-content\b", r"\bac\b",
    r"\bclear-content\b", r"\bout-file\b", r"\bnew-item\b[^|;&]*-force",
    r"\bgit\s+checkout\b[^|;&]*\s--(\s|$)", r"\bgit\s+restore\b", r"\bgit\s+rm\b", r"\bgit\s+mv\b",
]
_WRITE = re.compile("|".join(_WRITE_PATTERNS))
_API = re.compile(r"api\.anthropic\.com|\b(import|from)\s+anthropic\b")


def main() -> None:
    event = c.read_event()
    root = c.project_root(event)
    command = (event.get("tool_input") or {}).get("command") or ""
    normalized = command.replace("\\", "/").casefold()

    if _API.search(normalized) and not normalized.lstrip().startswith("uv run viveka"):
        c.block(
            "Viveka: blocked a direct call to the Anthropic API. Coders run only inside pipeline "
            "stages (`uv run viveka ...`), never from a session (principle H1)."
        )

    writes = _WRITE.search(_HARMLESS_REDIRECTS.sub(" ", normalized))
    if not writes:
        return
    for key in c.protected_keys(root):
        needle = key.rstrip("/")
        if needle and needle in normalized:
            c.block(
                f"Viveka: blocked a command that writes, moves or deletes near a protected path "
                f"('{needle}'). Frozen registry files, raw data, runs and the change ledger are immutable. "
                "If this is a false positive, run the read-only part separately."
            )


if __name__ == "__main__":
    c.run_guard(main)
