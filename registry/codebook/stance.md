# Stance (task T1, with T2's reason extraction folded in)

Drafted 4 Oct 2026 from the framework (sections "Evidential symmetry", "Symmetry reason by reason", "Coders are
instruments") and the engine's interpretation fixed in M2 (spec, "Interpretations fixed in M2"). Draft: to be
reviewed by the owner before the first coding run, and developed only on development-fold items (spec: "Codebook,
filter wording and fitted thresholds may be developed only on runs tagged fold=dev").

## What is being coded

One item is a passage from a scientific paper in which one cited work is marked `[CITED]`. Other citations in the
passage are marked `[REF]`. Words that would identify the field, the topic, the people or the places involved
have been replaced by bracketed placeholders such as `[TERM]`, `[NAME]` or `[PLACE]`; this is deliberate, and a
coder never guesses what they stand for.

The question is only this: **how does the passage treat the work marked `[CITED]` as evidence?**

The coder is not told, and must not try to work out, what the cited work found, which claim it bears on, or
whether the citing authors agree with it on the topic. The label describes the citing passage's treatment of
the cited work, relative to whatever that work itself reported.

## Labels

- **`+` accepted.** The passage uses the cited work as evidence that counts in the direction the cited work
  points: it relies on it, builds on it, reports it as showing something, lists it among findings that stand,
  or argues from it. Agreement is not needed; a passage that reports a finding it dislikes, without setting it
  aside, still accepts it as evidence.
- **`x` discounted.** The passage sets the cited work aside as evidence and gives, or clearly implies, a reason:
  a flaw of method, of sample, of analysis, of conduct, of circumstance, or any other ground for not counting it.
  The reason need not be correct or well founded; it is coded as given.
- **`-` turned round.** The passage cites the work as counting *against* the direction the work itself
  reported: "their own data in fact show the opposite", "reanalysed, the result supports the reverse". This is
  rare. Choose it only when the passage says outright that the work, properly read, points the other way.
- **`none` mentioned only.** The passage names the work without using it as evidence either way: as a source of
  a method, an instrument, a definition, a data set or software; as background or history; in a list of works on
  a topic with no finding attributed; or in a way too fragmentary to tell.

## Decision rules

1. Read only the passage. Do not use anything you know about the topic, the authors or the outcome of any
   debate. If a placeholder hides what you would need, decide from what is left; if that is not enough, the label
   is `none`.
2. A reason makes a discount. "Small, unblinded and uncontrolled, the study of [CITED] cannot settle the
   question" is `x`. Setting a work aside with no reason given or implied ("we do not consider [CITED] further")
   is `none`, not `x`.
3. A limitation acknowledged while the finding is still relied on is `+`, not `x`: "although small, [CITED]
   showed a clear effect" accepts the work.
4. If the passage first accepts and then discounts the same work, code the final treatment.
5. A reason that cannot be checked from a study's methods ("conditions were not right", "the effect fades when
   observed sceptically") still makes an `x`; it is coded as given and judged elsewhere.
6. Where the passage discounts a group of works including `[CITED]` for a shared reason, the label is `x` for
   `[CITED]`.
7. When in real doubt between `+` and `none`, choose `none`; between `x` and anything else, choose `x` only if
   the passage itself states or clearly implies the reason.

## The reason span

For `x` only, copy into `reason_span` the shortest words of the passage that state the reason, exactly as they
appear (placeholders included). Do not paraphrase, summarise or add words. If the reason is implied by several
separated words, copy the shortest single stretch that contains them. For `+`, `-` and `none`, `reason_span` is
`null`.

## Examples

These are invented, and deliberately from no field the instrument is calibrated or tested on.

| Passage | Label | reason_span |
|---|---|---|
| Earlier measurements of the decay rate [CITED] agree with ours within one standard error. | `+` | null |
| The higher yield reported by [CITED] was obtained without a control plot and cannot be compared with field trials. | `x` | without a control plot |
| We follow the extraction protocol of [CITED]. | `none` | null |
| [CITED] reported no association, but the cohort was followed for only six months, too short for the outcome to appear. | `x` | the cohort was followed for only six months |
| Although the sample in [CITED] was small, the effect it found has since been widely used as a benchmark. | `+` | null |
| Reanalysed with the correct baseline, the data of [CITED] show the reverse of the trend its authors described. | `-` | null |
| Several studies have addressed this question [REF, CITED, REF]. | `none` | null |
| Results such as those of [CITED] arise only when the [TERM] is not handled under the proper conditions. | `x` | only when the [TERM] is not handled under the proper conditions |
