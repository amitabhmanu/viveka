import pytest
from conftest import write_lf

from viveka.census import FrameWork, References, coverage_rows, outcome, sample_frame, summarize
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


def test_outcomes_and_coverage_arithmetic():
    frame = works(3, years=(1990,)) + works(2, years=(1991,))
    refs = References(("10.1/a", "10.1/b", None, "10.9/x"), "crossref")
    known = {"10.1/a", "10.1/b"}
    outcomes = [outcome(frame[0], refs, known), outcome(frame[1], None, known), outcome(frame[3], refs, known)]
    assert outcomes[0].resolved == 2 and outcomes[0].status == "measured" and outcomes[1].status == "unmeasured"
    rows = coverage_rows("cf", "citing", "mainstream", frame, outcomes)
    assert rows == [
        {"case_id": "cf", "frame_id": "citing", "kind": "mainstream", "year": 1990, "frame_works": 3, "sampled": 2,
         "measured": 1, "unmeasured": 1, "refs": 4, "resolved": 2},
        {"case_id": "cf", "frame_id": "citing", "kind": "mainstream", "year": 1991, "frame_works": 2, "sampled": 1,
         "measured": 1, "unmeasured": 0, "refs": 4, "resolved": 2},
    ]
    (whole,) = summarize(rows, max_unmeasured_share=0.5)
    assert whole.coverage == 0.5 and whole.unmeasured_share == pytest.approx(1 / 3) and whole.measurable
    (strict,) = summarize(rows, max_unmeasured_share=0.3)
    assert not strict.measurable
    (year_1990,) = summarize(rows[:1], 0.5)
    assert year_1990.unmeasured_share == 0.5 and year_1990.measurable


def test_no_references_is_not_measurable():
    frame = works(2, years=(1995,))
    rows = coverage_rows("cf", "venue", "community", frame, [outcome(w, None, set()) for w in frame])
    (s,) = summarize(rows, 1.0)
    assert s.coverage is None and s.unmeasured_share == 1.0 and not s.measurable


def test_frame_kind_does_not_change_the_numbers():
    frame = works(12)
    sample = sample_frame("cf", "f", frame, 10, seed=7)
    refs = References(("10.1/a", None), "crossref")
    outcomes = [outcome(w, refs if i % 3 else None, {"10.1/a"}) for i, w in enumerate(sample)]
    community = coverage_rows("cf", "f", "community", frame, outcomes)
    mainstream = coverage_rows("cf", "f", "mainstream", frame, outcomes)
    assert [{**r, "kind": None} for r in community] == [{**r, "kind": None} for r in mainstream]


def test_manual_reference_import(tmp_path):
    path = tmp_path / "refs.csv"
    write_lf(path, "work_id,ref_index,ref_text,doi,entered_by,source_note\n"
                   "W30,2,Second ref,https://doi.org/10.1/B,AM,ICCF-1 p.3\n"
                   "W30,1,First ref,,AM,ICCF-1 p.3\n")
    assert load_manual(path) == {"W30": References((None, "10.1/b"), "manual")}
    write_lf(path, "work_id,ref_index,ref_text,doi,entered_by,source_note\nW30,1,Ref,,AM,x\nW30,1,Ref,,AM,x\n")
    with pytest.raises(ManualImportError, match="twice"):
        load_manual(path)
    write_lf(path, "work_id,ref_text\nW30,x\n")
    with pytest.raises(ManualImportError, match="missing columns"):
        load_manual(path)
    write_lf(path, "work_id,ref_index,ref_text,doi,entered_by,source_note\nW30,one,Ref,,,x\n")
    with pytest.raises(ManualImportError, match="required"):
        load_manual(path)
