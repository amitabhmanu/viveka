"""`viveka sim ...` subcommands."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from viveka.provenance import RunContext
from viveka.registry.errors import UnsetParameter
from viveka.registry.thresholds import Thresholds, load_thresholds
from viveka.sim.calibrate import PROFILES, derive, measurement_params, recovery, run_grid, simulate_row
from viveka.sim.config import load_simulation_config
from viveka.sim.lineages import load_scenarios
from viveka.sim.power import pilot_power
from viveka.sim.registry_write import write_draft
from viveka.verdict.params import GateParams


def add_parser(sub: argparse._SubParsersAction, common: argparse.ArgumentParser) -> None:
    sim = sub.add_parser("sim", help="Simulator: thresholds and sizes (D-7), recovery, pilot power")
    ssub = sim.add_subparsers(dest="action", required=True)

    p = ssub.add_parser("thresholds", parents=[common], help="Simulate the grid and derive δ, c, k, t, h, m, v")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--write-draft", action="store_true", help="Write the values into registry/thresholds.yaml")
    p.add_argument("--estimate", action="store_true", help="Time one replicate per grid point and project runtime")
    p.add_argument("--replicates", type=int, help="Override (development only; refused with --write-draft)")
    p.add_argument("--bootstrap-draws", type=int, help="Override (development only; refused with --write-draft)")

    p = ssub.add_parser("recover", parents=[common], help="How often a planted profile reads as each verdict")
    p.add_argument("--profile", default="healthy")
    p.add_argument("--members", type=int, required=True)
    p.add_argument("--replicates", type=int, default=20)
    p.add_argument("--n", type=int, help="Gate-1 minimum disconfirmations while n is still unfitted (diagnostic)")

    p = ssub.add_parser("pilot", parents=[common], help="Pilot power on lineage scenarios (YAML)")
    p.add_argument("scenarios", type=Path)
    p.add_argument("--replicates", type=int, default=50)
    p.add_argument("--n", type=int, help="Gate-1 minimum disconfirmations while n is still unfitted (diagnostic)")


def _diagnostic_params(thresholds: Thresholds, n: int | None) -> GateParams | None:
    """Gate parameters for recover and pilot. n is fitted at calibration (M8), so until then --n supplies it.

    The override lives only in this process; nothing is written to the registry.
    """
    if n is not None:
        thresholds = thresholds.overridden(n_min_disconfirmations=n)
    try:
        return GateParams.from_thresholds(thresholds)
    except UnsetParameter as exc:
        hint = " (pass --n until n is fitted)" if "n_min_disconfirmations" in str(exc) else ""
        print(f"viveka: {exc}{hint}")
        return None


def run(args: argparse.Namespace, root: Path) -> int:
    config = load_simulation_config(root)
    thresholds = load_thresholds(root)

    if args.action == "thresholds":
        overridden = args.replicates is not None or args.bootstrap_draws is not None
        if args.write_draft and overridden:
            print("viveka: --write-draft only accepts the registered replicates and bootstrap draws")
            return 1
        if args.replicates is not None:
            config = config.replace(replicates=args.replicates)
        params = measurement_params(thresholds, args.bootstrap_draws)

        if args.estimate:
            started = time.perf_counter()
            for profile in PROFILES:
                for members in config.members_grid:
                    simulate_row((config, params, profile, members, 0))
            per_replicate = time.perf_counter() - started
            single = per_replicate * config.replicates
            print(f"one replicate across the grid: {per_replicate:.1f}s")
            print(f"projected at {config.replicates} replicates: {single / 60:.0f} min on one worker; "
                  f"~{single / 60 / max(1.0, 0.6 * args.workers):.0f} min with {args.workers} workers")
            return 0

        def progress(profile: str, members: int, done: int, total: int) -> None:
            print(f"[{done}/{total}] {profile} members={members} {time.strftime('%H:%M:%S')}", flush=True)

        run_params = {"replicates": config.replicates, "bootstrap_draws": params.bootstrap_draws,
                      "workers": args.workers, "members_grid": list(config.members_grid)}
        with RunContext(root, "SIM", "thresholds", "dev", ["simulation"], seed=config.seed,
                        params=run_params) as ctx:
            table = run_grid(config, params, workers=args.workers, progress=progress)
            derived = derive(table, config)
            ctx.store(json.dumps(list(table.rows)).encode("utf-8"), "json", rows=len(table.rows))
            ctx.store(json.dumps(derived, indent=2).encode("utf-8"), "json")
        print(json.dumps(derived["values"], indent=2))
        print(f"run {ctx.run_id}")
        if args.write_draft:
            written = write_draft(root, derived["values"], ctx.run_id,
                                  f"D-7 simulated thresholds and sizes from run {ctx.run_id} "
                                  f"({config.replicates} replicates, B={params.bootstrap_draws}, seed {config.seed})")
            print("written to registry/thresholds.yaml: " + ", ".join(f"{k}={v}" for k, v in written.items()))
        return 0

    params = _diagnostic_params(thresholds, args.n)
    if params is None:
        return 1
    if args.action == "recover":
        counts = recovery(args.profile, args.members, params, config, args.replicates, config.seed)
        for outcome, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"{count:4d}  {outcome}")
        return 0

    scenarios = load_scenarios(args.scenarios.read_text(encoding="utf-8"))
    for row in pilot_power(scenarios, params, config, args.replicates, config.seed):
        print(f"{row.case}: predicted {row.predicted} reached {row.reach_probability:.0%}; "
              f"gate 1 passed in {row.eligibility_rate:.0%} of scored windows; summaries {row.summaries}")
    return 0
