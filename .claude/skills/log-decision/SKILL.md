---
name: log-decision
description: Record why the Viveka registry changed, or record an owner decision (D-1 to D-8), in the append-only ledgers. Use when a hook asks for a reason before stopping, after editing anything under registry/, or when the user decides one of the open decisions.
argument-hint: "[D-n] <reason>"
allowed-tools: Bash(uv run python .claude/skills/log-decision/scripts/log_decision.py *)
---

Record a reason or a decision with the script below. Never edit `ledger/changes.jsonl` or `ledger/decisions.md` directly; both are append-only.

1. Work out the reason:
   - Use `$ARGUMENTS` if it gives one.
   - Otherwise take it from the conversation: what changed in the registry, and the result or discussion that prompted it.
   - If the reason isn't clear, ask the user. Don't invent one.
2. If the user has decided one of D-1 to D-8, include `--decision D-n --resolve`.
   - `--decision D-n` without `--resolve` adds a note and leaves the decision open.
3. Run:

```bash
uv run python .claude/skills/log-decision/scripts/log_decision.py --session ${CLAUDE_SESSION_ID} --reason "<one-line reason>" [--decision D-n] [--resolve]
```

4. Report what the script recorded: which change ids it covered and any decision line it added.
