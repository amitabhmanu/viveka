---
name: freeze-registry
description: Freeze Viveka registry components, recording the reason in the ledger and tagging the commit registry-v<N>. Only the user invokes this. Freezing is a research act, not a routine step.
argument-hint: "<component> [<component> ...]"
disable-model-invocation: true
---

Freeze the registry components named in `$ARGUMENTS`. A freeze fixes content before the data it governs is coded or scored, so be deliberate.

1. **Validate.** Run `uv run viveka registry validate $ARGUMENTS`. If validation fails, show the problems and stop.
2. **Show what will be frozen.**
   - Find the last registry tag with `git tag --list "registry-v*" --sort=-v:refname`.
   - Show `git diff <last tag> -- registry/` (or `git diff --stat -- registry/` if there is no tag yet), limited to the components being frozen.
   - Say plainly what changes and which analyses the freeze will govern.
3. **Get the reason.**
   - Ask the user for the reason, and for the result or decision that prompted this freeze.
   - Don't invent a reason, and don't reuse one from earlier in the conversation unless the user confirms it.
4. **Freeze.** Run `uv run viveka registry freeze $ARGUMENTS --reason "<reason>"`. The command:
   - refuses if preconditions fail (unset thresholds, missing `source_run`, unfrozen upstream components, an existing tag);
   - otherwise writes `registry/FROZEN.json`, appends a freeze record to the ledger, commits those files and tags `registry-v<N>`.
5. **Report.** Report the version, the component hashes and the tag. Remind the user that frozen files can now change only through `viveka registry bump`, and that nothing has been pushed.

If the command refuses, report each problem verbatim. Don't work around a refusal by editing files.
