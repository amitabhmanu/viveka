# Calibration candidates: search of 2 October 2026

Desk search for new calibration fields on both sides, run while the D-18 eligibility chain was rebuilding.
No field was fetched, no corpus was read and nothing in `registry/` was changed. Venue sizes and citation
counts are OpenAlex figures from `viveka corpus resolve` on 2 Oct 2026. Nothing here is a measure or a verdict;
a candidate qualifies only through the registered stages.

## The bar a candidate has to clear

- **Selection rule D-10**, with point 1 widened on 2 Oct 2026 (before this search looked at any candidate the
  widening admits): the core claim judged unsupported or not science by a national scientific body, government
  review or court (original rule) or by a national health technology assessment agency or a formal position
  statement of a scientific or medical society (widened rule); the judgement on the core claim itself,
  unretracted, and not contradicted by a body of the same standing. Point 2 is unchanged: venues devoted to
  the field's own community, indexed or ingestible; mixed venues are left out.
- **Size, from D-17 and the D-18 reruns**: a lineage cites roughly 10–18% of its claim's literature in one
  5-year window, so reaching v = 463 takes a claim whose anchors are cited by about 3,500–4,500 works, and a
  community whose own venues hold a cluster of at least m = 190 authors in the window. For scale: homeopathy
  (12,400 own works; claim literatures 2,971 and 2,671) and chiropractic (5,756; 1,763 and 1,151) both fail v.

## Pseudoscience side: no candidate clears the bar

| Candidate (core claim) | Formal judgement | Own venues in OpenAlex | Claim literature (anchor citations) | Outcome |
|---|---|---|---|---|
| Acupuncture (meridians, qi, point specificity) | None found on the core claim; WHO and NIH statements endorse efficacy for some conditions | Acupuncture in Medicine 2,480; Medical Acupuncture 1,406; J Acupunct Meridian Stud 1,157 | not sized | **Fails point 1** under both rules (no judgement; conflicting bodies). The only candidate with venues at the needed scale |
| Vaccines cause autism (MMR, thimerosal) | IOM 2004 "favors rejection of a causal relationship"; US Omnibus Autism Proceeding. Original rule | None: J Am Physicians and Surgeons is not indexed | Wakefield 1998: 3,025; Taylor 1999: 762; Madsen 2002: 712; Bernard 2001: 351 | Judgement and size are there; **fails point 2** (no community venues, so no field frame and no C) |
| Polygraph lie detection | National Research Council 2003. Original rule | European Polygraph 212; the APA's *Polygraph* is not indexed | anchors in the tens to low hundreds | **Too small** on venues and on claim |
| Race differences in intelligence are genetic | Society statements only (widened rule); the 1996 APA task force was agnostic, so standing is arguable | Mankind Quarterly 1,575 (about 130 works per 5 years) | Rushton and Jensen 2005: 466 | **Too small**; judgement contestable |
| HIV does not cause AIDS | National academies and courts. Original rule | None | Duesberg 1987: 174 | **Too small**; fails point 2 |
| Facilitated communication | APA 1994, ASHA and AAP position statements. Widened rule | None indexed | Biklen 1990: 296 | **Too small**; fails point 2 |
| Therapeutic touch / energy psychology | Society statements. Widened rule | Energy Psychology 161 | Rosa 1998: 233 | **Too small** |
| Climate contrarianism (warming is mainly solar or natural) | National academies' statements. Original rule, though "pseudoscience" is arguable | Energy & Environment 3,087, a mixed venue | Friis-Christensen and Lassen 1991: 888; Soon and Baliunas 2003: 162 | **Fails point 2** (mixed venue); claim too small |
| Electromagnetic hypersensitivity / low-level RF harm | National health councils; WHO fact sheet. Mostly original rule | Electromagnetic Biology and Medicine 1,016, mixed | Lai and Singh 2004: 347 | **Fails point 2**; too small |
| Ozone therapy | FDA regulation against; other states license it (conflicting) | Journal of Ozone Therapy 147 | not sized | **Fails point 1**; too small |

What the search shows:

1. The widening of point 1 admits nothing new at the needed size. Every candidate it adds (facilitated
   communication, therapeutic touch, energy psychology) is an order of magnitude too small.
2. The only pseudoscience with own venues comparable to homeopathy's is acupuncture, and it has no formal
   judgement against its core claim; public bodies endorse it for some conditions. Admitting it would mean
   relaxing "undisputed extremes", which the framework rules out, not who may judge.
3. The one rejected claim with a large enough literature, vaccines and autism, has no community venues. It has
   the shape of a pilot case (a citing frame around founding papers), not of a calibration field.

So under any reading of D-10, homeopathy and chiropractic remain the largest qualifying pseudosciences, and
both fail v. This confirms D-17 from the candidate side: the limit is the gate's size requirement, not the
selection rule.

## Science side: candidates are plentiful

All under the unchanged rule (uncontested textbook consensus, own venues). Chosen to be mid-sized, because S3
cost grows steeply with the author graph (immunology took about 52 hours).

| Candidate | Own venues (OpenAlex works) | Possible commitments, with anchor citations | Notes |
|---|---|---|---|
| Palaeontology | Journal of Paleontology 10,371; Journal of Vertebrate Paleontology 4,273; Paleobiology 2,652; Palaeontology 2,043 | Impact cause of the end-Cretaceous extinction (Alvarez 1980: 4,045); periodicity or selectivity of mass extinctions (Raup and Sepkoski 1982: 1,787) | Best fit: large claim literature, dated disconfirmations (Deccan volcanism, gradualist fossil records). Overlap with plate tectonics to be measured |
| Glaciology | Journal of Glaciology 9,586; Annals of Glaciology 5,781 | Glen's flow law (Glen 1955: 1,654) | Claim literature probably below the bar on its own |
| Electrochemistry | Journal of The Electrochemical Society 56,135; Electrochimica Acta 54,399 | Marcus electron-transfer theory (Marcus 1956: 6,093) | Claim is large, but the venues are immunology-sized: days of S3 |
| Virology | Journal of Virology 52,126; Journal of General Virology 17,559 | not drafted | Likely overlap with immunology and molecular genetics; very large |
| Seismology | dropped at 25.0% core-author overlap with plate tectonics (limit 0.2) | — | Returns only if the overlap limit is raised, which would be chosen knowing its figure |

Palaeontology is the one to draft first. A science field costs a fetch (OpenAlex allowance), an overlap
check, a census and an S3 build, and each commitment needs its works verified by lookup and reviewed by the
owner (D-15) before any of that.

## Sources for the judgements

- National Research Council (2003), *The Polygraph and Lie Detection*: https://www.nationalacademies.org/read/10420/chapter/2
- Institute of Medicine (2004), *Immunization Safety Review: Vaccines and Autism*: https://www.cidrap.umn.edu/childhood-vaccines/iom-finds-no-link-between-thimerosal-and-autism
- Spain's plan against pseudotherapies and the RedETS reports (acupuncture not among the evaluated techniques found): https://www.sanidad.gob.es/gabinete/notasPrensa.do?id=6396
- Acupuncture, WHO and NIH positions (secondary): https://www.ebsco.com/research-starters/complementary-and-alternative-medicine/meridian-chinese-medicine

The other judgements in the table are from memory of the documents named and were not re-read on 2 Oct 2026;
each must be verified by lookup before a candidate is registered.
