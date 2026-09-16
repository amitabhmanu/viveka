import pytest
from conftest import write_lf

from viveka.census import (
    Biblio,
    FrameWork,
    Reference,
    References,
    biblio_of,
    coverage_rows,
    doiless_sample,
    journal_compatible,
    match_found,
    outcome,
    sample_frame,
    summarize,
)
from viveka.corpus.manual import ManualImportError, load_manual


def works(n_per_year, years=(1990, 1991)):
    return [FrameWork(f"W{year}{i:03d}", year, f"10.1/{year}.{i}") for year in years for i in range(n_per_year)]


def test_sampling_is_stratified_reproducible_and_seed_dependent():
    pool = works(30)
    first = sample_frame("cf", "citing", pool, 10, seed=1)
    assert len(first) == 20 and {w.year for w in first} == {1990, 1991}
    assert first == sample_frame("cf", "citing", list(reversed(pool)), 10, seed=1)  # input order is irrelevant
    assert first != sample_frame("cf", "citing", pool, 10, seed=2)
    assert first != sample_frame("cf", "venue", pool, 10, seed=1)
    assert sample_frame("cf", "citing", works(4), 10, seed=1) == sorted(works(4), key=lambda w: (w.year, w.work_id))


def test_doiless_references_are_sampled_reproducibly():
    refs = References.from_dois(["10.1/a"] + [None] * 10, "crossref")
    first = doiless_sample("cf", "W1", refs, 3, seed=1)
    assert len(first) == 3 and all(refs.entries[i].doi is None for i in first)
    assert first == doiless_sample("cf", "W1", refs, 3, seed=1) and first != doiless_sample("cf", "W2", refs, 3, 1)
    few = References.from_dois(["10.1/a", None, None], "crossref")
    assert doiless_sample("cf", "W1", few, 3, seed=1) == [1, 2]
    assert doiless_sample("cf", "W1", refs, 0, seed=1) == []


def test_outcomes_and_estimated_coverage():
    frame = works(3, years=(1990,)) + works(2, years=(1991,))
    refs = References((Reference("10.1/a"), Reference("10.1/b"), Reference(None, text="A book"), Reference("10.9/x"),
                       Reference(None, 1986, "56", "3", "Phys. Rev. Lett.")), "crossref")
    known = {"10.1/a", "10.1/b"}
    first = outcome(frame[0], refs, known, {2: None, 4: True})
    assert (first.resolved, first.doiless, first.doiless_sampled, first.doiless_matched,
            first.doiless_unparseable) == (2, 2, 2, 1, 1)
    assert first.status == "measured" and outcome(frame[1], None, known).status == "unmeasured"
    outcomes = [first, outcome(frame[1], None, known), outcome(frame[3], refs, known, {4: False})]
    rows = coverage_rows("cf", "citing", "mainstream", frame, outcomes)
    assert rows == [
        {"case_id": "cf", "frame_id": "citing", "kind": "mainstream", "year": 1990, "frame_works": 3, "sampled": 2,
         "measured": 1, "unmeasured": 1, "refs": 5, "resolved": 2, "doiless": 2, "doiless_sampled": 2,
         "doiless_matched": 1, "doiless_unparseable": 1, "resolved_estimated": 3.0},
        {"case_id": "cf", "frame_id": "citing", "kind": "mainstream", "year": 1991, "frame_works": 2, "sampled": 1,
         "measured": 1, "unmeasured": 0, "refs": 5, "resolved": 2, "doiless": 2, "doiless_sampled": 1,
         "doiless_matched": 0, "doiless_unparseable": 0, "resolved_estimated": 2.0},
    ]
    (whole,) = summarize(rows, max_unmeasured_share=0.5)
    assert whole.coverage == 0.5 and whole.unmeasured_share == pytest.approx(1 / 3) and whole.measurable
    assert whole.doiless == 4 and whole.resolved_estimated == 5.0
    (strict,) = summarize(rows, max_unmeasured_share=0.3)
    assert not strict.measurable
    (year_1990,) = summarize(rows[:1], 0.5)
    assert year_1990.coverage == 0.6 and year_1990.unmeasured_share == 0.5 and year_1990.measurable


def test_no_references_is_not_measurable():
    frame = works(2, years=(1995,))
    rows = coverage_rows("cf", "venue", "community", frame, [outcome(w, None, set()) for w in frame])
    (s,) = summarize(rows, 1.0)
    assert s.coverage is None and s.unmeasured_share == 1.0 and not s.measurable


def test_frame_kind_does_not_change_the_numbers():
    frame = works(12)
    sample = sample_frame("cf", "f", frame, 10, seed=7)
    refs = References.from_dois(("10.1/a", None), "crossref")
    outcomes = [outcome(w, refs if i % 3 else None, {"10.1/a"}, {1: i % 2 == 0}) for i, w in enumerate(sample)]
    community = coverage_rows("cf", "f", "community", frame, outcomes)
    mainstream = coverage_rows("cf", "f", "mainstream", frame, outcomes)
    assert [{**r, "kind": None} for r in community] == [{**r, "kind": None} for r in mainstream]


def test_bibliographic_fields_are_read_from_structure_or_text():
    prl = "Phys. Rev. Lett."
    assert biblio_of(Reference(None, 1986, "56", "3", prl)) == Biblio(1986, "56", "3", prl)
    assert biblio_of(Reference(None, text="E. Fischbach et al., Phys. Rev. Lett. 56, 3 (1986).")) == \
        Biblio(1986, "56", "3", None)
    assert biblio_of(Reference(None, text="M. Fleischmann, J. Electroanal. Chem. 261:301-308 (1989a)")) == \
        Biblio(1989, "261", "301", None)
    assert biblio_of(Reference(None, text="O. Hahn, Applied Radiochemistry. Cornell University Press, 1936")) is None
    assert biblio_of(Reference(None, 1990, "12, 3", "4")) is None  # a value that would break the filter syntax


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        (Reference(None, 1983, "D27", "1672", "Phys. Rev."), Biblio(1983, "27", "1672", "Phys. Rev.")),
        (Reference(None, 1983, "125B", "355"), Biblio(1983, "125", "355", None)),
        (Reference(None, 1941, "12", "51 ff"), Biblio(1941, "12", "51", None)),
        (Reference(None, 1984, "Vol. I", "259"), None),
        (Reference(None, 1941, "Feb", "51"), None),
        (Reference(None, text="S.C. Holding, F.D. Stacey and G.J. Tuck: Phys. Rev. D33 3487 (1986)"),
         Biblio(1986, "33", "3487", None)),
        (Reference(None, text="[3] Melvin H. Miles et al., Introduction, Fusion Technol. 25 (1994) 478."),
         Biblio(1994, "25", "478", None)),
        (Reference(None, text="Fleischmann, M., Induced fusion. J. Electroanal. Chem., 1989. 261: p. 301."),
         Biblio(1989, "261", "301", None)),
        (Reference(None, text="Davenas E, et al. Human basophil degranulation. Nature. 1988;333(6176):816-8."),
         Biblio(1988, "333", "816", None)),
        (Reference(None, text="[11] Landau, Lifshitz, Quantum Mechanics (Pergamon, Oxford, 1965)."), None),
        (Reference(None, text="Suslick, K.S., ed. Ultrasound (VCH, New York, 1988)."), None),
    ],
)
def test_citation_layouts(reference, expected):
    assert biblio_of(reference) == expected


@pytest.mark.parametrize(
    ("cited", "name", "compatible"),
    [
        ("Phys. Rev. Lett.", "Physical Review Letters", True),
        ("J. Electroanal. Chem.", "Journal of Electroanalytical Chemistry", True),
        ("Nucl. Instrum. Methods Phys. Res. A", "Nuclear Instruments and Methods in Physics Research Section A: "
                                                "Accelerators, Spectrometers, Detectors", True),
        ("Nature", "Nature", True),
        ("Nature", "Nature Physics", False),
        ("Phys. Rev. Lett.", "Physics Letters B", False),
        ("", "Nature", False),
    ],
)
def test_journal_names(cited, name, compatible):
    assert journal_compatible(cited, name) is compatible


def test_match_rules():
    prl = Biblio(1986, "56", "3", "Phys. Rev. Lett.")
    assert match_found(prl, ["Physical review letters"])  # a single work at year, volume and page
    assert match_found(prl, ["Physics Letters B", "Physical Review Letters"])  # the journal breaks the tie
    assert not match_found(prl, ["Physics Letters B", "Nuclear Physics A"])
    assert not match_found(Biblio(1986, "56", "3", None), ["A", "B"])
    assert not match_found(prl, [])


def test_manual_reference_import(tmp_path):
    path = tmp_path / "refs.csv"
    write_lf(path, "work_id,ref_index,ref_text,doi,entered_by,source_note\n"
                   "W30,2,Second ref,https://doi.org/10.1/B,AM,ICCF-1 p.3\n"
                   "W30,1,First ref,,AM,ICCF-1 p.3\n")
    assert load_manual(path) == {"W30": References((Reference(None, text="First ref"),
                                                    Reference("10.1/b", text="Second ref")), "manual")}
    write_lf(path, "work_id,ref_index,ref_text,doi,entered_by,source_note\nW30,1,Ref,,AM,x\nW30,1,Ref,,AM,x\n")
    with pytest.raises(ManualImportError, match="twice"):
        load_manual(path)
    write_lf(path, "work_id,ref_text\nW30,x\n")
    with pytest.raises(ManualImportError, match="missing columns"):
        load_manual(path)
    write_lf(path, "work_id,ref_index,ref_text,doi,entered_by,source_note\nW30,one,Ref,,,x\n")
    with pytest.raises(ManualImportError, match="required"):
        load_manual(path)
