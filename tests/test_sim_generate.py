import numpy as np
import pytest

from viveka.measures.types import Applies, LedgerCode, Side, Stance
from viveka.sim import coders
from viveka.sim.config import CoderFamily, tiny
from viveka.sim.generate import simulate_commitment

LAG = 2.0
EXACT = (CoderFamily("exact", "human", 0.0),)


def test_generation_is_reproducible_by_seed():
    cfg = tiny()
    profile = cfg.profiles["healthy"]
    a, _ = simulate_commitment(profile, 20, cfg, LAG, np.random.default_rng(5))
    b, _ = simulate_commitment(profile, 20, cfg, LAG, np.random.default_rng(5))
    c, _ = simulate_commitment(profile, 20, cfg, LAG, np.random.default_rng(6))
    assert a == b and a != c


def test_filter_property_is_independent_of_direction_and_support_share_holds():
    cfg = tiny(families=EXACT)
    inputs, truth = simulate_commitment(cfg.profiles["insulated"], 1500, cfg, LAG, np.random.default_rng(11))
    applies = {a.result_id: a.value for a in inputs.applicability}
    table = np.zeros((2, 2))
    for r in inputs.results:
        table[int(r.supports is Side.P), int(applies[r.result_id] is Applies.YES)] += 1
    expected = table.sum(1, keepdims=True) * table.sum(0, keepdims=True) / table.sum()
    chi2 = float(((table - expected) ** 2 / expected).sum())
    assert chi2 < 10.83  # p > 0.001 with one degree of freedom
    share_p = table[1].sum() / table.sum()
    assert abs(share_p - cfg.support_share) < 0.03
    assert truth.results == 6000


def test_coder_flip_rate_and_discount_reasons():
    rng = np.random.default_rng(1)
    fam = (CoderFamily("f", "automated", 0.2),)
    values = [coders.label_applicability("r", "blinding", Applies.YES, fam, rng)[0].value for _ in range(20000)]
    assert abs(np.mean([v is not Applies.YES for v in values]) - 0.2) < 0.015

    labels = [coders.label_stance("r", (Stance.SUPPORT, None), fam, ("blinding", "decline"), rng)[0]
              for _ in range(5000)]
    discounts = [lab for lab in labels if lab.stance is Stance.DISCOUNT]
    assert discounts and all(lab.filter_id in ("blinding", "decline") for lab in discounts)
    assert all(lab.filter_id is None for lab in labels if lab.stance is not Stance.DISCOUNT)


def test_planted_profiles_shape_the_inputs():
    cfg = tiny(families=EXACT)
    healthy, _ = simulate_commitment(cfg.profiles["healthy"], 400, cfg, LAG, np.random.default_rng(2))
    insulated, _ = simulate_commitment(cfg.profiles["insulated"], 400, cfg, LAG, np.random.default_rng(2))

    def cited_share(inputs, side):
        rows = [r for r in inputs.results if r.supports is side]
        return sum(r.cited for r in rows) / len(rows)

    assert abs(cited_share(healthy, Side.NOT_P) - cited_share(healthy, Side.P)) < 0.05
    assert cited_share(insulated, Side.NOT_P) < cited_share(insulated, Side.P) - 0.3

    supports = {r.result_id: r.supports for r in insulated.results}
    decline = [s for s in insulated.stances if s.filter_id == "decline"]
    assert decline and all(supports[s.result_id] is Side.NOT_P for s in decline)
    assert not [s for s in healthy.stances if s.filter_id == "decline"]

    codes = [next(iter(e.codes.values())) for e in insulated.ledger]
    expected = 400 * cfg.disconfirmations_per_member  # Poisson mean; sd is its square root
    assert abs(len(codes) - expected) < 5 * expected ** 0.5
    assert abs(len(insulated.conditions_honoured) - 400 * cfg.met_conditions_per_member) \
        < 5 * (400 * cfg.met_conditions_per_member) ** 0.5
    assert all(e.when + LAG <= insulated.window_end for e in insulated.ledger)
    assert all(e.rounds for e in insulated.ledger if next(iter(e.codes.values())) is LedgerCode.B)


def test_window_must_be_longer_than_lag():
    cfg = tiny()
    with pytest.raises(ValueError):
        simulate_commitment(cfg.profiles["healthy"], 5, cfg, lag=float(cfg.window_length_years),
                            rng=np.random.default_rng(0))
