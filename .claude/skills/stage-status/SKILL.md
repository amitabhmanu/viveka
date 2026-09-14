---
name: stage-status
description: Summarise the state of the Viveka harness — registry version and integrity, draft components, unset thresholds, change-ledger integrity, recent runs and open decisions. Use when the user asks where things stand or before starting milestone work.
allowed-tools: Bash(uv run viveka status *) Bash(uv run viveka registry verify *) Bash(uv run viveka ledger verify *)
---

1. Run `uv run viveka status`.
2. If it reports a registry MISMATCH or ledger problems:
   - run `uv run viveka registry verify` or `uv run viveka ledger verify` for the details;
   - report every problem verbatim.
   - A mismatch means a frozen file changed: say so plainly and don't try to repair it.
3. Summarise in a few lines:
   - what is frozen and whether it verifies;
   - what is still draft, and how many thresholds are unset;
   - whether any registry changes lack a reason;
   - the latest runs;
   - which open decisions block the next milestone (see `docs/viveka-harness-spec.html` §16–§17).
