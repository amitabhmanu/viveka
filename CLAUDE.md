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
M0 (guardrails), M1 (registry, ledger, run manifests), M2 (verdict engine) and M3 (simulator, D-7 thresholds) are in place. M4a (corpus and census for the pilot and reserve pairs) is done: cases frozen as registry v1, registered pilot-fold census runs verified. Before M5: ingest the ICCF proceedings as a second cold fusion frame (D-8, via a logged bump). M4b (calibration candidates) and D-9 (full-text contexts, before M6) are open.
- Corpus and census: `viveka corpus resolve` (drafting lookup), `viveka case validate <case>` (read-only), `viveka corpus fetch|contexts --case X --fold F`, `viveka census --case X --fold F`. Every stage has `--dry-run`; live runs go through `/run-stage` with the user's confirmation. Never read `.env`; the pipeline loads it. OpenAlex spend is capped per day in `registry/corpus.yaml`.
- Simulator: `uv run viveka sim thresholds` (the registered run that sets δ, c, k, t, h, m, v; `--write-draft` only at registered settings), `viveka sim recover` and `viveka sim pilot` (diagnostics; `--n` stands in for n until it is fitted and is never written).
- Read-only: `uv run viveka status`, `uv run viveka registry validate|verify`, `uv run viveka ledger verify`, `uv run viveka verify <run_id>`.
- Research acts, user-initiated only: `viveka registry freeze` (via `/freeze-registry`) and `viveka registry bump`. Never freeze or bump on your own initiative.
- Every future stage runs inside `viveka.provenance.RunContext`, which verifies the registry components it declares.
The guardrails live in `.claude/settings.json` and `.claude/hooks/`; changing them always needs the user's approval.

## Working
- Python via uv: `uv run pytest`, `uv run ruff check`, `uv run viveka status`.
- Hook scripts in `.claude/hooks/` use the standard library only and must fail closed (exit 2 on any internal error).
- The verdict engine and simulator (M2, M3) must stay pure and fully tested.
- Where the framework document is ambiguous, stop and record a decision in `ledger/decisions.md`; don't improvise.
