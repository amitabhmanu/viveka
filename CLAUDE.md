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
M0 (guardrails) and M1 (registry, ledger, run manifests) are in place. No pipeline stages exist yet.
- Read-only: `uv run viveka status`, `uv run viveka registry validate|verify`, `uv run viveka ledger verify`, `uv run viveka verify <run_id>`.
- Research acts, user-initiated only: `viveka registry freeze` (via `/freeze-registry`) and `viveka registry bump`. Never freeze or bump on your own initiative.
- Every future stage runs inside `viveka.provenance.RunContext`, which verifies the registry components it declares.
The guardrails live in `.claude/settings.json` and `.claude/hooks/`; changing them always needs the user's approval.

## Working
- Python via uv: `uv run pytest`, `uv run ruff check`, `uv run viveka status`.
- Hook scripts in `.claude/hooks/` use the standard library only and must fail closed (exit 2 on any internal error).
- The verdict engine and simulator (M2, M3) must stay pure and fully tested.
- Where the framework document is ambiguous, stop and record a decision in `ledger/decisions.md`; don't improvise.
