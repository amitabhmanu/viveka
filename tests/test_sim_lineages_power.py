import numpy as np

from viveka.sim.config import tiny
from viveka.sim.lineages import LineageSpec, Scenario, load_scenarios, membership, simulate_scenario
from viveka.sim.power import pilot_power, robustness
from viveka.verdict.field_summary import Summary, descendants
from viveka.verdict.params import GateParams
from viveka.verdict.reasons import Verdict
from viveka.verdict.stability import match_lineages

PARAMS = GateParams(n=2, m=3, v=4, r=0.7, lag=2.0, delta=0.15, c=0.7, k=4.0, j=10.0, t=0.8, h=0.5, h0=3,
                    interval_level=0.9, bootstrap_draws=30, omega_strata=5)

COLD_FUSION = Scenario(
    name="cold-fusion", windows=4, root="mainstream", predicted=Summary.SPLIT,
    lineages=(
        LineageSpec("mainstream", start=0, members=40, profile="healthy", end=1),
        LineageSpec("residue", start=1, members=20, profile="insulated", parent="mainstream"),
    ),
)


def test_membership_churn_branching_and_matching():
    windows = membership(COLD_FUSION, churn=0.1, rng=np.random.default_rng(3))
    assert set(windows[0]) == {"mainstream"} and set(windows[1]) == {"mainstream", "residue"}
    assert match_lineages(windows[1], windows[2]) == {"mainstream": "mainstream", "residue": "residue"}
    assert windows[1]["residue"] & windows[0]["mainstream"]  # the branch starts from its parent's members
    assert len(windows[3]["residue"]) == 20
    assert descendants("mainstream", COLD_FUSION.parents()) == {"mainstream", "residue"}


def test_closure_after_the_last_engaged_window():
    verdicts = simulate_scenario(COLD_FUSION, tiny(), PARAMS, np.random.default_rng(4))
    mainstream = {v.window[0]: v.result.verdict for v in verdicts if v.lineage_id == "mainstream"}
    assert mainstream[2] is Verdict.CLOSED and mainstream[3] is Verdict.CLOSED
    assert mainstream[0] is not Verdict.CLOSED
    assert {v.window[0] for v in verdicts if v.lineage_id == "residue"} == {1, 2, 3}


def test_pilot_power_and_robustness_report_probabilities():
    [report] = pilot_power([COLD_FUSION], PARAMS, tiny(), replicates=3, seed=7)
    assert report.case == "cold-fusion" and report.predicted == "split"
    assert 0.0 <= report.reach_probability <= 1.0 and 0.0 <= report.eligibility_rate <= 1.0
    assert sum(report.summaries.values()) == 3
    assert 0.0 <= robustness(COLD_FUSION, PARAMS, tiny(), replicates=2, seed=7) <= 1.0


def test_scenarios_load_from_yaml():
    [scenario] = load_scenarios("""
scenarios:
  - name: fifth-force
    windows: 3
    root: tested
    predicted: uniform
    lineages:
      - {id: tested, start: 0, end: 1, members: 30, profile: healthy}
""")
    assert scenario.predicted is Summary.UNIFORM and scenario.lineages[0].end == 1
