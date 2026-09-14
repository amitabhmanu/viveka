# Viveka decision log

Append-only. Each line is one event: `- <date> · <id> · <STATUS> · <text>`.
The current status of a decision is the status on its latest line.
Add entries with `/log-decision`; never edit or delete earlier lines.

- 2026-09-14 · D-1 · OPEN · Linux runtime for the block model and GROBID (WSL2, Docker Desktop, or a remote Linux runner)
- 2026-09-14 · D-2 · OPEN · Second automated model family, or a second human coder in its place
- 2026-09-14 · D-3 · OPEN · Human coders: who, how many, how trained, whether paid
- 2026-09-14 · D-4 · OPEN · Anthropic coder model and effort level (default claude-opus-5)
- 2026-09-14 · D-5 · OPEN · Where predictions and registry versions are timestamped (git tags only, or also an external registry)
- 2026-09-14 · D-6 · OPEN · Budget ceiling and per-run cap
- 2026-09-14 · D-7 · OPEN · Null-simulated thresholds for δ, c, k, t, h
- 2026-09-14 · D-8 · OPEN · Use of community archives: confirm each source's terms
- 2026-09-14 · D-7 · DECIDED · Adopted (user, M3 plan 14 Sep 2026): delta, c, k, t, h are set by simulation before any real data, each at the value where the reading it guards against happens by noise alone at rate alpha at every grid size; m and v follow from power; calibration tests the thresholds. Adds the registered simulation component (upstream of thresholds) and marks the five thresholds simulated.
