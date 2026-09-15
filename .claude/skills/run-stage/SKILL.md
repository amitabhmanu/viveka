---
name: run-stage
description: Run a Viveka pipeline stage for a case (corpus fetch, corpus contexts, census) after validating prerequisites and showing the projected API use. Only the user invokes this; stage runs touch live data sources and count against spend caps.
argument-hint: "<fetch|contexts|census> <case> <fold>"
disable-model-invocation: true
---

Run the stage named in `$ARGUMENTS` (stage, case id, fold). A stage run acquires or measures real data under the frozen registry, so be deliberate.

1. **Validate.** Run `uv run viveka case validate <case>` and `uv run viveka registry validate`. If either fails, show the problems and stop.
2. **Check the fold.** For `pilot`, `heldout` or `contested`, the case, its claim and `corpus` must be frozen and the git tree clean; run `uv run viveka registry verify` and `git status --short`. If anything is unfrozen or dirty, say so and stop. Don't freeze on the user's behalf.
3. **Project.** Run the stage with `--dry-run`:
   - `uv run viveka corpus fetch --case <case> --fold <fold> --dry-run` (offer `--probe` if frame sizes are unknown; a probe makes a few cheap live calls, so ask first);
   - `uv run viveka corpus contexts --case <case> --fold <fold> --dry-run`;
   - `uv run viveka census --case <case> --fold <fold> --dry-run`.
   Show the projected calls and OpenAlex spend against the registered daily cap.
4. **Confirm.** Ask the user to confirm the run. Don't proceed on an earlier approval for a different stage or case.
5. **Run** the same command without `--dry-run`. For long runs, run it in the background and report progress.
6. **Report.** Give the run id, `uv run viveka verify <run_id>`, the usage line, and for a census the report table verbatim. Don't summarise coverage figures in your own words beyond what the report states, and don't draw eligibility conclusions: gate 1 applies *r* at S4.

If a command refuses (unfrozen components, missing credentials, spend cap), report the message verbatim. Don't work around a refusal.
