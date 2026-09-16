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
- 2026-09-14 · D-7 · DECIDED · M3 findings review (user chose the recommendation, 14 Sep 2026): disconfirmations and met conditions become per-member Poisson rates (0.5, 0.2; 10 and 4 at 20 members as before) so c and h no longer saturate at 1.0; grid extended to 640 members; new convention delta_margin 0.15 (equivalence margin) floors delta, replacing the two-sided rule under which m could only equal the grid top
- 2026-09-15 · D-8 · OPEN · M4a plan (approved 15 Sep 2026): new corpus component (sources, OpenAlex daily cap 0.80 below the free allowance, rate limits, census conventions works_per_year 10, max_unmeasured_share 0.5, seed 20260915, Crossref-DOI-in-OpenAlex resolution) moved out of instrument; events and cases get registered schemas (format 1); cases depend on corpus and their claim's events
- 2026-09-15 · D-8 · OPEN · Deferred at M4a (user, 15 Sep 2026): community venue archives are not downloaded; their works count as unmeasured in the census, with a manual reference-import path, until M4a census results show how much of each case this affects
- 2026-09-15 · D-1 · OPEN · Deferred at M4a (user, 15 Sep 2026): no GROBID; works whose reference lists exist only in PDFs are unmeasured until the M4a census shows whether a Linux runtime is needed
- 2026-09-16 · D-9 · OPEN · Full-text access for citation contexts: Semantic Scholar (keyless) gives contexts for only 8-26% of citing papers and about 1-4% in the 1980s-90s pilot periods, so stance coding (M6-M7) needs full text: publisher text-and-data-mining agreements through an institution, library copies with manual extraction, or open-access PDFs with GROBID (D-1)
