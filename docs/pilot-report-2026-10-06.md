# Viveka pilot report, 6 October 2026

A small pilot on the development fold, run to see whether the instrument produces a readable signal on real
literature and what a full-scale experiment would need. It makes modest claims and no verdicts. Every number
below comes from a `viveka` stage; the run that produced it is named beside it.

## Summary

- The pipeline runs end to end on real data: communities, the citations they make of results bearing on a claim,
  the citing passages, two models' labels, and a number with an interval.
- On three pseudoscience commitments, authors accept studies that support their claim more often than studies
  that contradict it, by 11 to 20 points. Each interval includes zero.
- On two molecular genetics commitments, authors cite mostly studies that contradict the claim, accept them
  about 70 to 76% of the time, and almost never dismiss them.
- The two sides cannot yet be compared like for like, and discounts are too rare to measure. Neither of the
  framework's measures (Δ, Ω) was computed. Nothing here validates or refutes the framework.

## What was measured

For each commitment, the papers of its lineage members in the coded five-year windows, and their citations of
results bearing on the claim (decision D-28). Two models, Opus 5.5 and Sonnet 5.5, labelled independently:

- **direction** (task T7): from its abstract, is a cited result for the claim, against it, not bearing on it, or
  unclear;
- **stance** (task T1): does the citing passage accept the cited result as evidence, discount it with a reason,
  turn it round, or only mention it. Field-identifying words are redacted.

The pilot statistic (decision D-29) pairs each model's own direction labels with its own stance labels:

- **A0**, acceptance asymmetry: accepted share on results for the claim minus accepted share on results against;
- **D0**, discount asymmetry: discounted share on results against minus discounted share on results for.

Both are positive when evidence in the claim's favour is treated more kindly. Intervals are 95%, from 2,000
draws resampling cited results and models. D0 is not Δ: it has no filters, so it cannot tell a discount for a
good reason from one for a bad reason.

## Results

Pilot run `2026-10-06T1331Z-s9-pilot-calibration-fields-df86`.

| Commitment | Side | Passages on results for / against (Opus; Sonnet) | Accepted, for vs against (Opus; Sonnet) | A0 [95%] | D0 [95%] |
|---|---|---|---|---|---|
| homeopathy beyond-placebo | pseudoscience | 113 / 31; 82 / 31 | 45% vs 35%; 45% vs 32% | +0.11 [−0.07, +0.31] | +0.03 [−0.03, +0.13] |
| homeopathy immunotherapy-allergy | pseudoscience | 43 / 22; 54 / 23 | 42% vs 27%; 37% vs 26% | +0.13 [−0.05, +0.43] | +0.01 [−0.05, +0.14] |
| chiropractic nonmusculoskeletal | pseudoscience | 18 / 18; 28 / 17 | 44% vs 28%; 46% vs 24% | +0.20 [−0.22, +0.57] | −0.13 [−0.55, 0.00] |
| molecular genetics central-dogma | science | 3 / 496; 1 / 474 | 33% vs 74%; 100% vs 68% | −0.04 [−0.77, +0.36] | 0.00 |
| molecular genetics parental-equivalence | science | 6 / 736; 32 / 832 | 83% vs 76%; 69% vs 72% | +0.02 [−0.73, +0.25] | +0.01 [0.00, +0.02] |

Agreement between the two models, per coding run:

| Task | Agreement | Cohen's kappa |
|---|---|---|
| Direction (five commitments) | 83–96% | 0.70–0.84 |
| Stance (five commitments) | 88–92% | 0.74–0.79 |

Two direction labels are missing (Sonnet, parental-equivalence, of 363 results); no stance label is missing.

## What can be said

1. **The pseudoscience commitments lean the same way.** All three show a positive A0 of similar size, and the
   two models agree on it. No single interval excludes zero, so the lean is suggestive, not established.
2. **The molecular genetics community engages with contrary evidence.** Almost everything it cites on these two
   claims counts against them (the exceptions to the central dogma; imprinting against parental equivalence),
   and it accepts that evidence in about three passages out of four. One model found 32 passages on supporting
   results for parental-equivalence, with 69% accepted against 72% for contradicting results: no lean.
3. **The comparison is not like for like.** The science commitments were chosen as claims the field has revised,
   so their cited literature is one-sided and A0 is unreadable there (1 to 32 passages on supporting results).
   Comparing acceptance rates across fields (about 30% in homeopathy against about 72% in molecular genetics for
   contradicting results) is confounded by how often each field's papers accept what they cite at all.
4. **Discounts are too rare to read.** No commitment has more than 21 discounts by either model, and the models
   disagree on most of them (for example 21 against 8 on the allergy claim, 7 in common).

## What the pilot taught us about a full-scale experiment

- **Most "bearing results" do not bear on the claim.** The registered rule (any work citing a seed or event
  work) is far wider than the claim: the models labelled 44–88% of cited results as not bearing. The threshold v
  was counted on that wide set, so S4's eligibility overstated what each window holds. Bearing results need a
  direction-based definition, and v needs to be re-derived for it.
- **Context coverage is the binding limit.** Semantic Scholar gives a citing passage for 13% of homeopathy's
  member citations, 33% of chiropractic's and 36–49% of molecular genetics'. After direction and stance, the
  homeopathy windows hold tens of usable results against v = 329. Full text is the only way past this.
- **Publishers hide reference lists from the references endpoint.** Contexts have to be fetched per cited result
  (the citations endpoint), which is slow without an API key (one request every five seconds).
- **Half the passages were lost to marker resolution, and half of that loss was recoverable.** Recognising
  parenthesised numbers and using Crossref reference-list positions nearly doubled homeopathy's usable passages
  (decision D-30). Superscript numbers that lost their formatting remain unrecoverable from snippets.
- **Science commitments should be chosen so the evidence splits.** Claims a field has already revised give a
  one-sided literature and no within-field comparison.
- **Coder independence is weak.** Two models of one family, no human labels. Haiku 4.5 was dropped for low
  agreement (D-27). Agreement on discounts in live coding is below the 0.6 the audit asks for.
- **Blinding failed.** Every model identified the field from redacted passages (D-25); the symmetry audit was
  the only guard against field-based bias.
- **Registry edits made unrelated runs stale.** Lowering q, which eligibility never reads, forced the cluster
  censuses and eligibility runs to be repeated.

## Departures from the registered design

All recorded in `ledger/decisions.md`; none should be carried into a full-scale run without review.

| Decision | Departure |
|---|---|
| D-17 | Power lowered from 0.80 to 0.75, post hoc; m = 135, v = 329 |
| D-18, D-19 | Lineage members' papers outside the field's venues count; social-layer runs reused by settings |
| D-3, D-2, D-21 | No human coder; one model family; intervals resample over models |
| D-9, D-22 | Semantic Scholar contexts only; no full text |
| D-25 | Leakage test failed for every coder; coding proceeded with the symmetry audit as the guard |
| D-26, D-27 | One audit rerun; pool reduced to Opus and Sonnet and q lowered to 2 after results were seen |
| D-28 | Coding scope: results bearing on the claim with a new direction task; three sampled windows per science commitment |
| D-29 | The pilot statistic A0 and D0, in place of Δ and Ω; stance on directed results only for the science side |
| D-30 | Citation-marker rule widened after the first labels were seen |

## Not done in the pilot

Filters and applicability (S5, T3), so no Δ; directions for uncited results, so no Ω; the ledger of responses to
disconfirmations; plate tectonics and thermodynamics (their contexts were partly fetched and not coded);
the calibration fold; any registry freeze. The development fold was used throughout, and rules were adjusted on
it, so these numbers are exploratory.
