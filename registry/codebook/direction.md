# Direction of a result (task T7)

Drafted 4 Oct 2026 under decision D-28: stance (T1) is coded relative to the cited result, so each result
bearing on a claim needs a direction, and only the registered events have one. Draft: to be reviewed by the owner
before the first coding run, and developed only on development-fold items.

## What is being coded

One item is a claim and the abstract of one scientific work. The question is only this: **does the work, as its
abstract reports it, count for or against the claim?**

The coder judges the work's own findings or conclusions, as the abstract states them. It does not judge whether
the work is right, whether the claim is true, or what the field believes. The claim is shown so that the coder
knows what is being asked about; the abstract is not redacted, since the claim names the topic anyway (decision
D-25: coders can identify the field).

## Labels

- **`for`.** The work reports a finding or reaches a conclusion that supports the claim: an effect the claim
  predicts is found, a test the claim passes is passed, a review concludes in the claim's favour.
- **`against`.** The work reports a finding or reaches a conclusion that counts against the claim: an effect
  the claim predicts is not found, or is found to be explained by something else; a review concludes that the
  evidence does not support the claim.
- **`not_bearing`.** The work reports no finding or conclusion on the claim: it uses the claim's topic only as
  background, is about a method, an instrument or another question, describes practice or history, or argues
  without reporting evidence.
- **`cannot_tell`.** The work reports a finding on the claim but the abstract does not make its direction
  clear: the results are mixed or inconclusive as stated, or the abstract is too short or garbled to decide.

## Decision rules

1. Use only the claim and the abstract. Do not use what you know about the work, its authors, its reception or
   the topic.
2. A null result counts against a claim that predicts an effect: "no significant difference from placebo" is
   `against` the claim that the treatment has effects beyond placebo.
3. A conclusion counts even when the coder finds it weakly supported: an abstract that concludes in the claim's
   favour from a small study is `for`.
4. "Further research is needed" alone is not a direction. If the abstract reports a positive finding and then
   calls for more research, it is `for`; if it reports no clear finding, it is `cannot_tell`.
5. A work that bears on the claim only in part (a subgroup, one condition among several) is coded by what it
   reports on that part. If the parts point different ways and the abstract weighs none above the others, it is
   `cannot_tell`.
6. When in real doubt between `for` or `against` and `cannot_tell`, choose `cannot_tell`; between `cannot_tell`
   and `not_bearing`, choose `not_bearing` only if the abstract reports no finding on the claim at all.

## The basis span

For `for` and `against` only, copy into `basis_span` the shortest words of the abstract that state the finding or
conclusion that decides the label, exactly as they appear. For `not_bearing` and `cannot_tell`, `basis_span` is
`null`.

## Examples

Invented, and from no field the instrument is calibrated or tested on. Claim: "Daily cold-water immersion
shortens recovery after endurance exercise."

| Abstract (extract) | Label | basis_span |
|---|---|---|
| ... recovery time fell by 14% in the immersion group compared with passive rest (p < 0.01) ... | `for` | recovery time fell by 14% in the immersion group compared with passive rest |
| ... no difference in recovery markers between immersion and control at 24 or 48 hours ... | `against` | no difference in recovery markers between immersion and control |
| ... we describe a low-cost thermistor for measuring bath temperature in field settings ... | `not_bearing` | null |
| ... immersion improved perceived soreness but worsened the next day's performance ... | `cannot_tell` | null |
| ... the reported benefits of immersion disappear once expectation is controlled for ... | `against` | the reported benefits of immersion disappear once expectation is controlled for |
