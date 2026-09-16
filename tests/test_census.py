import pytest
from conftest import write_lf

from viveka.census import (
    Biblio,
    Candidate,
    FrameWork,
    Reference,
    References,
    biblio_of,
    coverage_rows,
    doiless_sample,
    journal_compatible,
    journal_contained,
    match_found,
    outcome,
    reference_kind,
    rescue_match,
    rescue_query,
    sample_frame,
    summarize,
)
from viveka.corpus.manual import ManualImportError, load_manual

PAPERS = frozenset({"article", "review", "letter", "conference-paper"})


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
    pool = refs.doiless()
    first = doiless_sample("cf", "W1", pool, 3, seed=1)
    assert len(first) == 3 and all(refs.entries[i].doi is None for i in first)
    assert first == doiless_sample("cf", "W1", pool, 3, seed=1) and first != doiless_sample("cf", "W2", pool, 3, 1)
    assert doiless_sample("cf", "W1", [2, 1], 3, seed=1) == [1, 2]
    assert doiless_sample("cf", "W1", pool, 0, seed=1) == []


def test_outcomes_count_only_papers_and_estimate_coverage():
    frame = works(3, years=(1990,)) + works(2, years=(1991,))
    refs = References((
        Reference("10.1/a"), Reference("10.1/b"),
        Reference(None, text="Landau, Lifshitz, Quantum Mechanics (Pergamon, Oxford, 1965)."),  # a book: excluded
        Reference("10.9/x"),  # a DOI the corpus lacks: an unresolved paper
        Reference(None, 1986, "56", "3", "Phys. Rev. Lett."),  # a DOI-less paper
        Reference("10.5/chapter"),  # a DOI whose corpus type is not a paper: excluded
        Reference(None, 1978),  # nothing to classify it by
    ), "crossref")
    doi_types = {"10.1/a": "article", "10.1/b": "review", "10.5/chapter": "book-chapter"}
    first = outcome(frame[0], refs, doi_types, PAPERS, {4: True})
    assert (first.refs, first.resolved, first.refs_excluded, first.refs_unclassifiable, first.doiless,
            first.doiless_sampled, first.doiless_matched) == (4, 2, 2, 1, 1, 1, 1)
    assert first.status == "measured" and outcome(frame[1], None, doi_types, PAPERS).status == "unmeasured"
    outcomes = [first, outcome(frame[1], None, doi_types, PAPERS),
                outcome(frame[3], refs, doi_types, PAPERS, {4: False})]
    rows = coverage_rows("cf", "citing", "mainstream", frame, outcomes, {1990: 2, 1992: 1})
    common = {"case_id": "cf", "frame_id": "citing", "kind": "mainstream"}
    assert rows == [
        {**common, "year": 1990, "frame_works": 3, "frame_works_excluded": 2, "sampled": 2, "measured": 1,
         "unmeasured": 1, "refs": 4, "resolved": 2, "refs_excluded": 2, "refs_unclassifiable": 1, "doiless": 1,
         "doiless_sampled": 1, "doiless_matched": 1, "doiless_rescued": 0, "doiless_unparseable": 0,
         "resolved_estimated": 3.0},
        {**common, "year": 1991, "frame_works": 2, "frame_works_excluded": 0, "sampled": 1, "measured": 1,
         "unmeasured": 0, "refs": 4, "resolved": 2, "refs_excluded": 2, "refs_unclassifiable": 1, "doiless": 1,
         "doiless_sampled": 1, "doiless_matched": 0, "doiless_rescued": 0, "doiless_unparseable": 0,
         "resolved_estimated": 2.0},
        {**common, "year": 1992, "frame_works": 0, "frame_works_excluded": 1, "sampled": 0, "measured": 0,
         "unmeasured": 0, "refs": 0, "resolved": 0, "refs_excluded": 0, "refs_unclassifiable": 0, "doiless": 0,
         "doiless_sampled": 0, "doiless_matched": 0, "doiless_rescued": 0, "doiless_unparseable": 0,
         "resolved_estimated": 0.0},
    ]
    (whole,) = summarize(rows, max_unmeasured_share=0.5)
    assert whole.coverage == 0.625 and whole.unmeasured_share == pytest.approx(1 / 3) and whole.measurable
    assert whole.frame_works_excluded == 3 and whole.refs_excluded == 4 and whole.resolved_estimated == 5.0
    (strict,) = summarize(rows, max_unmeasured_share=0.3)
    assert not strict.measurable
    (year_1990,) = summarize(rows[:1], 0.5)
    assert year_1990.coverage == 0.75 and year_1990.unmeasured_share == 0.5 and year_1990.measurable


def test_no_references_is_not_measurable():
    frame = works(2, years=(1995,))
    rows = coverage_rows("cf", "venue", "community", frame, [outcome(w, None, {}, PAPERS) for w in frame])
    (s,) = summarize(rows, 1.0)
    assert s.coverage is None and s.unmeasured_share == 1.0 and not s.measurable


@pytest.mark.parametrize(
    ("reference", "kind"),
    [
        (Reference(None, 1983, "D27", "1672", "Phys. Rev."), "paper"),
        (Reference(None, 1992, "55", "1", "Rep. Prog. Phys."), "paper"),
        (Reference(None, 1983, first_page="244", series_title="AIP Conf. Proc. No. 99"), "paper"),
        (Reference(None, text="Proc. 9th Int. Workshop on Low Temperature Detectors 605, 453 (2002)"), "paper"),
        (Reference(None, text="[3] A. Takahashi, Mechanism of deuteron cluster fusion, Proceedings of the ICCF 10, "
                              "Cambridge, MA, 2003. Available at http://www.lenr-canr.org"), "paper"),
        (Reference(None, text="Hawking S.W., Commun. Math. Phys. 25, 167 (1972)"), "paper"),
        (Reference("10.1/any"), "paper"),
        (Reference(None, 1982, volume_title="Electron Radial Wave Functions and Nuclear Beta Decay"), "excluded"),
        (Reference(None, 1984, journal="SLAC-PUB-3304"), "excluded"),
        (Reference(None, 1977, journal="CERN 77-18", article_title="An Introduction to Gauge Theories"), "excluded"),
        (Reference(None, 1989, first_page="69", journal="US Department of Energy, DOE/S-0073"), "excluded"),
        (Reference(None, text="Griffiths SR. Mothers' attitudes to immunisation [MD Thesis]. London, 1986."),
         "excluded"),
        (Reference(None, text="P.G. Esposito, to be published."), "excluded"),
        (Reference(None, text="[11] Landau, Lifshitz, Quantum Mechanics (Pergamon, Oxford, 1965)."), "excluded"),
        (Reference(None, text="Will, C.: 1981, Theory and Experiment in Gravitational Physics, Cambridge "
                              "University Press, Cambridge."), "excluded"),
        (Reference(None, text="[4] DOE, Report of the review of low energy nuclear reactions, 2004. Available at "
                              "http://www.science.doe.gov"), "excluded"),
        (Reference(None, text="New Scientist 14 July 1988 p. 39."), "excluded"),
        (Reference(None, 1978), "unclassifiable"),
        (Reference(None, text="Kaluza, T.: 1921, Sitzungsberichte der Berliner Akademie der Wissenschaften, No. 966."),
         "unclassifiable"),
    ],
)
def test_reference_kinds(reference, kind):
    assert reference_kind(reference) == kind


def _candidate(doi="10.9/hit", score=60.0, year=1986, volume="56", page="3", journal="Physical Review Letters",
               title="Reanalysis of the Eotvos experiment", kind="journal-article"):
    return Candidate(doi, score, year, volume, page, journal, title, kind)


def test_bibliographic_rescue_accepts_verified_candidates_only():
    wrong_page = Reference(None, 1986, "56", "4", "Phys. Rev. Lett.")
    assert rescue_match(wrong_page, [_candidate()], 40, 0.8, 1) == "10.9/hit"  # volume agrees
    assert rescue_match(wrong_page, [_candidate(score=24)], 40, 0.8, 1) is None  # too weak a match
    assert rescue_match(wrong_page, [_candidate(year=1990)], 40, 0.8, 1) is None  # wrong year
    assert rescue_match(wrong_page, [_candidate(kind="book-chapter")], 40, 0.8, 1) is None
    assert rescue_match(wrong_page, [_candidate(volume="57", page="9", journal="Nature")], 40, 0.8, 1) is None
    swapped = Reference(None, 1972, "167", "25", "Commun. Math. Phys")  # the depositor swapped volume and page
    assert rescue_match(swapped, [_candidate(year=1972, volume="25", page="167-171",
                                             journal="Communications in Mathematical Physics")], 40, 0.8, 1)
    # A free-text citation with a wrong volume and page but the title right.
    text = Reference(None, text="Bochner BS, et al. Flow cytometric methods for the analysis of human basophil "
                                "surface antigens and viability. J Immunol Meth 1989; 142: 180.")
    good = _candidate(year=1989, volume="125", page="265", journal="Journal of Immunological Methods",
                      title="Flow cytometric methods for the analysis of human basophil surface antigens and viability")
    assert rescue_match(text, [good], 40, 0.8, 1) == "10.9/hit"
    # A different paper by the same group: similar words, different journal, volume and page.
    abstract = Reference(None, text="Benveniste J, et al. Highly dilute antigen increases coronary flow of isolated "
                                    "heart from immunized guinea-pigs. FASEB J 1992; 6: A1610.")
    other = _candidate(year=1992, volume="81", page="68", journal="British Homoeopathic Journal",
                       title="Effect of dilute histamine on coronary flow of isolated guinea-pig heart")
    assert rescue_match(abstract, [other], 40, 0.8, 1) is None
    # False matches found by auditing accepted recoveries (rule v2 rejects each):
    same_title_elsewhere = Reference(None, text="Y. Arata, Y.-C. Zhang, Sono implantation of hydrogen and deuterium "
                                                "from water into metallic fine powders, in: 8th International "
                                                "Conference on Cold Fusion, 2000, p. 293.")
    apl = _candidate(year=2000, volume="76", page="2472", journal="Applied Physics Letters",
                     title="Sono implantation of hydrogen and deuterium from water into metallic fine powders")
    assert rescue_match(same_title_elsewhere, [apl], 40, 0.8, 1) is None
    volume_title = Reference(None, text="T.J. Phillips, Proc. 3rd Biennial Conf. on Low Energy Antiproton Physics "
                                        "(World Scientific, Singapore, 1995), p. 569")
    book = _candidate(year=1995, volume=None, page="1", journal="Low Energy Antiproton Physics",
                      title="Low Energy Antiproton Physics", kind="proceedings-article")
    assert rescue_match(volume_title, [book], 40, 0.8, 1) is None
    same_topic = Reference(None, text="Braginsky, V. B., Panov, V. I., Verification of the equivalence of inertial "
                                      "and gravitational mass, Sov. Phys.-JETP, 1972, 34: 463.")
    grg = _candidate(year=1972, volume="3", page="403", journal="General Relativity and Gravitation",
                     title="The equivalence of inertial and passive gravitational mass")
    assert rescue_match(same_topic, [grg], 40, 0.8, 1) is None
    own_title = Reference(None, 2009, article_title="Anomalous heat generation in charging of Pd powders with high "
                                                    "density hydrogen isotopes (I) Results of absorption experiments")
    related = _candidate(year=2009, volume="373", page="3109", journal="Physics Letters A",
                         title="Anomalous effects in charging of Pd powders with high density hydrogen isotopes")
    assert rescue_match(own_title, [related], 40, 0.8, 1) is None
    # Correct recoveries that rule v2 keeps: a page off by two, and a proceedings paper found as one.
    page_off = Reference(None, 1989, "45", "279", "Hyperfine Interact.",
                         text="E. Kuzmann et al., Hyperfine Interact., 45 /1989/ 279.")
    assert rescue_match(page_off, [_candidate(year=1989, volume="45", page="277", journal="Hyperfine Interactions",
                                              title="Mossbauer investigation of Fe-Zr amorphous alloys")], 40, 0.8, 1)
    assert rescue_query(Reference(None, 1978)) is None
    assert rescue_query(wrong_page) == "Phys. Rev. Lett. 56 4 1986"
    assert journal_contained("J. Electroanal. Chem.", "Journal of Electroanalytical Chemistry and Interfacial "
                                                      "Electrochemistry")


def test_frame_kind_does_not_change_the_numbers():
    frame = works(12)
    sample = sample_frame("cf", "f", frame, 10, seed=7)
    refs = References.from_dois(("10.1/a", None), "crossref")
    outcomes = [outcome(w, refs if i % 3 else None, {"10.1/a": "article"}, PAPERS, {1: i % 2 == 0})
                for i, w in enumerate(sample)]
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
