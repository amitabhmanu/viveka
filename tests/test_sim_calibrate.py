import math

from viveka.registry.thresholds import load_thresholds
from viveka.sim.calibrate import GridTable, derive, derive_sizes, derive_thresholds, measurement_params
from viveka.sim.config import tiny


def iv(lower, upper):
    return None if lower is None else [(lower + upper) / 2, lower, upper]


def row(profile, members, delta=None, omega=None, share=None, loop=None, tau=None, tau_m=False, hon=None,
        hon_m=False, citations=50):
    return {"profile": profile, "members": members, "replicate": 0, "results": 100, "citations": citations,
            "favoured": "p",
            "oriented": [{"side": "p", "delta": delta, "omega": omega, "share": share, "loop": loop}],
            "tau": tau, "tau_measurable": tau_m, "honoured": hon, "honoured_measurable": hon_m}


def table(rows, grid):
    return GridTable(tuple(rows), replicates=20, members_grid=grid, profiles=("healthy", "insulated"),
                     bootstrap_draws=100, seed=1)


def test_each_threshold_sits_at_its_alpha_edge():
    alpha = 0.1  # 20 replicates -> at most 2 may cross
    loops = [0.0] * 15 + [1.0, 2.0, 3.0, 4.0, 5.0]
    healthy = [row("healthy", 10, delta=iv(0.01 * i, 0.5), omega=iv(-1.0, 1.0), loop=iv(loops[i], 6.0),
                   tau=iv(0.1, 0.5 + 0.01 * i), tau_m=True, hon=iv(0.1, 0.2), hon_m=i < 2) for i in range(20)]
    insulated = [row("insulated", 10, share=iv(0.2, 0.60 + 0.01 * i)) for i in range(20)]
    derived = derive_thresholds(table(healthy + insulated, (10,)), alpha, power=0.8, margin=0.0)

    assert derived["details"]["delta_false_insulated_edge"] == 0.17  # 0.18 and 0.19 lie strictly above: 2
    assert derived["details"]["delta_healthy_reach_by_size"] == {"10": 1.0}  # reported only: Ω reaches ±1
    assert derived["delta"] == 0.17  # the noise edge, above a zero margin
    assert derived["k"] == 4  # lower bounds 4 and 5 reach k: exactly 2
    assert math.isclose(derived["t"], 0.52)  # uppers 0.50, 0.51 lie strictly below: exactly 2
    assert derived["h"] is None  # only 2 measurable replicates: never more than alpha allows
    assert math.isclose(derived["c"], 0.62)


def test_thresholds_take_the_strictest_size():
    small = [row("healthy", 5, delta=iv(0.30, 0.9), loop=iv(0, 1)) for _ in range(20)] + \
            [row("insulated", 5, share=iv(0.1, 0.9)) for _ in range(20)]
    large = [row("healthy", 50, delta=iv(0.05, 0.1), loop=iv(3, 4)) for _ in range(20)] + \
            [row("insulated", 50, share=iv(0.1, 0.4)) for _ in range(20)]
    derived = derive_thresholds(table(small + large, (5, 50)), 0.05, power=0.8, margin=0.0)
    # Ω is missing everywhere, so healthy can never read inside ±δ: the reported reach is undefined.
    assert derived["details"]["delta_healthy_reach_by_size"] == {"5": None, "50": None}
    assert derived["delta"] == 0.30 and derived["k"] == 4 and derived["c"] == 0.4


def test_margin_floors_delta_and_reach_is_only_reported():
    healthy = [row("healthy", 40, delta=iv(-0.02 - 0.005 * i, 0.03 + 0.005 * i), omega=iv(-0.01, 0.01),
                   loop=iv(0, 1)) for i in range(20)]
    below = derive_thresholds(table(healthy, (40,)), alpha=0.05, power=0.8, margin=0.1)
    assert below["details"]["delta_false_insulated_edge"] == 0.0  # every lower bound is negative
    assert below["delta"] == 0.1  # the margin, not the noise edge
    assert math.isclose(below["details"]["delta_healthy_reach_by_size"]["40"], 0.03 + 0.005 * 15)  # 16th of 20
    assert derive_thresholds(table(healthy, (40,)), alpha=0.05, power=0.8, margin=0.0)["delta"] == 0.0


def test_sizes_are_the_first_grid_points_meeting_power():
    thresholds = {"delta": 0.15, "t": 0.8}

    def healthy(members, inside, tau_ok):
        return [row("healthy", members, delta=iv(-0.1, 0.1) if inside else iv(-0.3, 0.3),
                    tau=iv(0.85, 1.2) if tau_ok else iv(0.5, 1.2), tau_m=True, citations=members * 3)
                for _ in range(20)]

    def insulated(members, beyond, tau_ok):
        return [row("insulated", members, delta=iv(0.2, 0.6) if beyond else iv(0.0, 0.6),
                    tau=iv(0.1, 0.5) if tau_ok else iv(0.1, 0.9), tau_m=True, citations=members * 2)
                for _ in range(20)]

    rows = healthy(10, False, False) + insulated(10, False, False) \
        + healthy(20, True, False) + insulated(20, True, False) \
        + healthy(40, True, True) + insulated(40, True, True)
    sizes = derive_sizes(table(rows, (10, 20, 40)), thresholds, power=0.8)
    assert sizes["v"] == 40  # at 20 members: min(median 60, median 40)
    assert sizes["m"] == 40
    none = derive_sizes(table(healthy(10, False, False) + insulated(10, False, False), (10,)), thresholds, 0.8)
    assert none["m"] is None and none["v"] is None


def test_derive_packages_values_details_and_settings():
    small = [row("healthy", 5, delta=iv(-0.3, 0.3), omega=iv(-0.3, 0.3), loop=iv(0, 1), tau=iv(0.2, 0.6),
                 tau_m=True) for _ in range(20)] + \
            [row("insulated", 5, delta=iv(0.3, 0.6), share=iv(0.6, 0.9), tau=iv(0.1, 0.3), tau_m=True)
             for _ in range(20)]
    large = [row("healthy", 10, delta=iv(-0.05, 0.05), omega=iv(-0.05, 0.05), loop=iv(0, 1), tau=iv(0.9, 1.1),
                 tau_m=True) for _ in range(20)] + \
            [row("insulated", 10, delta=iv(0.3, 0.6), share=iv(0.6, 0.9), tau=iv(0.1, 0.3), tau_m=True)
             for _ in range(20)]
    out = derive(table(small + large, (5, 10)), tiny(), margin=0.05)
    assert set(out["values"]) == {"delta", "c", "k", "t", "h", "m", "v"}
    assert out["values"]["delta"] == 0.05 and out["values"]["t"] == 0.6  # t from the small size's wide intervals
    assert out["values"]["m"] == 10 and out["values"]["v"] == 50
    assert set(out["details"]) == {"delta_false_insulated_edge", "delta_margin", "delta_healthy_reach_by_size"}
    assert out["settings"]["replicates"] == 20 and out["settings"]["delta_margin"] == 0.05


def test_measurement_params_use_registered_conventions(registry_root):
    params = measurement_params(load_thresholds(registry_root))
    assert params.bootstrap_draws == 2000 and params.lag == 2.0 and math.isnan(params.delta)
    assert measurement_params(load_thresholds(registry_root), bootstrap_draws=50).bootstrap_draws == 50
