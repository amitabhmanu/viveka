# Viveka

Framework: `docs/evidence-that-cuts-both-ways.html` (companion: `docs/the-insulated-core.html`).
Harness spec: `docs/viveka-harness-spec.html`. Where the spec and the framework disagree, the framework governs.

## Non-negotiable
- Never produce, edit or "fix" a label, measure or verdict by hand or in conversation.
  They come only from `viveka` stages. If output looks wrong, find the bug in code.
- Never edit files listed in `registry/FROZEN.json`. Propose a version bump instead
  (`/log-decision`, then `viveka registry bump` once it exists).
- Never read `registry/predictions/` while working on coding prompts, filters or redaction.
- Never overwrite anything under `data/raw/` or `runs/`, and never edit `ledger/changes.jsonl`; hooks append to it.
- Never run a stage that spends money without the user's explicit go-ahead in this session.
- Any change to `registry/` needs a reason: run `/log-decision` before finishing.

## Current milestone
M0 (scaffold) is in place. No pipeline stages exist yet; the only CLI command is `uv run viveka status`.
The guardrails live in `.claude/settings.json` and `.claude/hooks/`; changing them always needs the user's approval.

## Working
- Python via uv: `uv run pytest`, `uv run ruff check`, `uv run viveka status`.
- Hook scripts in `.claude/hooks/` use the standard library only and must fail closed (exit 2 on any internal error).
- The verdict engine and simulator (M2, M3) must stay pure and fully tested.
- Where the framework document is ambiguous, stop and record a decision in `ledger/decisions.md`; don't improvise.
