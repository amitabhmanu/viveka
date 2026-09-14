import ast
from pathlib import Path

import pytest
import yaml
from conftest import write_lf

from viveka.registry.errors import UnsetParameter
from viveka.registry.thresholds import load_thresholds
from viveka.verdict.field_summary import LineageVerdict, Summary, descendants, summarise
from viveka.verdict.params import GateParams
from viveka.verdict.reasons import Reason, Verdict, VerdictResult
from viveka.verdict.stability import jaccard, match_lineages, stable_verdict
from viveka.verdict.triggers import (
    CalibrationVerdict,
    IndependentCheck,
    PairOutcome,
    Truth,
    trigger_1,
    trigger_2,
    trigger_3,
    trigger_4,
    trigger_5,
    trigger_6,
)

HEALTHY = VerdictResult(Verdict.HEALTHY)
INSULATED = VerdictResult(Verdict.INSULATED)
UNCLEAR = VerdictResult(Verdict.INDETERMINATE, Reason.READING_UNCLEAR)
UNSTABLE = VerdictResult(Verdict.INDETERMINATE, Reason.UNSTABLE)
CLOSED = VerdictResult(Verdict.CLOSED)

# ---------------------------------------------------------------- gate 4


def test_matching_and_stability():
    ref = {"L1": frozenset("abcd"), "L2": frozenset("wxyz")}
    variant = {"V1": frozenset("wxy"), "V2": frozenset("abce"), "V3": frozenset("q")}
    assert jaccard(frozenset("ab"), frozenset("bc")) == 1 / 3
    assert match_lineages(ref, variant) == {"L1": "V2", "L2": "V1"}
    assert match_lineages(ref, {"V9": frozenset("q")}) == {"L1": None, "L2": None}

    assert stable_verdict([HEALTHY, HEALTHY, HEALTHY]) is HEALTHY
    assert stable_verdict([HEALTHY, INSULATED]).reason is Reason.UNSTABLE
    assert stable_verdict([UNCLEAR, VerdictResult(Verdict.INDETERMINATE, Reason.CONDUCT_CONFLICT)]).reason \
        is Reason.UNSTABLE
    assert "unmatched" in stable_verdict([HEALTHY, None]).note
    with pytest.raises(ValueError):
        stable_verdict([])


def test_verdict_result_requires_consistent_reason():
    with pytest.raises(ValueError):
        VerdictResult(Verdict.INDETERMINATE)
    with pytest.raises(ValueError):
        VerdictResult(Verdict.HEALTHY, Reason.UNSTABLE)


# ---------------------------------------------------------------- field summaries

PARENTS = {"mainstream": [], "residue": ["mainstream"], "offshoot": ["residue"], "elsewhere": []}


def lv(lineage, start, result):
    return LineageVerdict(lineage, (start, start + 4), result)


def test_descendants():
    assert descendants("mainstream", PARENTS) == {"mainstream", "residue", "offshoot"}


@pytest.mark.parametrize(
    ("verdicts", "expected"),
    [
        ([lv("mainstream", 1989, HEALTHY), lv("residue", 1995, HEALTHY)], Summary.UNIFORM),
        ([lv("mainstream", 1989, HEALTHY), lv("mainstream", 1990, CLOSED), lv("residue", 1995, INSULATED)],
         Summary.SPLIT),
        ([lv("residue", 1989, HEALTHY), lv("residue", 1996, INSULATED)], Summary.SHIFTED),
        ([lv("residue", 1989, HEALTHY), lv("residue", 1996, INSULATED), lv("offshoot", 1999, HEALTHY)],
         Summary.SPLIT),
        ([lv("mainstream", 1989, UNCLEAR), lv("residue", 1995, CLOSED)], Summary.UNDETERMINED),
        ([lv("mainstream", 1989, HEALTHY), lv("elsewhere", 1995, INSULATED)], Summary.UNIFORM),
    ],
)
def test_field_summaries(verdicts, expected):
    summary = summarise("mainstream", PARENTS, verdicts)
    assert summary.summary is expected
    assert "elsewhere" not in summary.lineages


# ---------------------------------------------------------------- triggers


def cal(cid, field, truth, result, replaced=False):
    return CalibrationVerdict(cid, field, truth, result, replaced)


def test_trigger_1_error_and_indeterminate_shares():
    ok = [cal("s1", "thermo", Truth.SCIENCE, HEALTHY), cal("p1", "astro", Truth.PSEUDOSCIENCE, INSULATED)]
    assert trigger_1(ok, e=0.1, i=0.2).fired is False
    wrong = [*ok, cal("s2", "thermo", Truth.SCIENCE, INSULATED)]
    assert trigger_1(wrong, e=0.1, i=0.9).fired is True
    shy = [*ok, cal("s3", "geo", Truth.SCIENCE, UNCLEAR)]
    assert trigger_1(shy, e=0.5, i=0.2).fired is True
    excluded = [*ok, cal("s4", "geo", Truth.SCIENCE, CLOSED), cal("p2", "creation", Truth.PSEUDOSCIENCE, UNCLEAR, True)]
    result = trigger_1(excluded, e=0.1, i=0.1)
    assert result.fired is False and result.numbers["scored"] == 2
    assert trigger_1([], 0.1, 0.1).fired is None


def test_trigger_2_to_6():
    assert trigger_2(0.55, True, 0.6).fired is True
    assert trigger_2(0.7, False, 0.6).fired is True
    assert trigger_2(0.7, True, 0.6).fired is False
    assert trigger_2(None, None, 0.6).fired is None
    assert trigger_3().fired is None

    separated = PairOutcome("pilot", {"fifth-force": Summary.UNIFORM, "cold-fusion": Summary.SPLIT},
                            {"fifth-force": Summary.UNIFORM, "cold-fusion": Summary.SPLIT})
    blurred = PairOutcome("reserve", {"17kev": Summary.UNIFORM, "cold-fusion": Summary.SPLIT},
                          {"17kev": Summary.UNDETERMINED, "cold-fusion": Summary.SPLIT})
    assert trigger_4([separated]).fired is False
    result = trigger_4([separated, blurred])
    assert result.fired is True and result.numbers["not_separated"] == ["reserve"]

    assert trigger_5([HEALTHY, UNSTABLE, UNSTABLE, CLOSED]).fired is True
    assert trigger_5([HEALTHY, UNSTABLE, CLOSED]).fired is False

    checks = [IndependentCheck("a", 0.8, None), IndependentCheck("b", 0.1, 0.0), IndependentCheck("c", None, None)]
    assert trigger_6(True, checks, (0.5, 0.9), (0.2, 0.6)).numbers["share"] == 0.5
    assert trigger_6(True, checks[:1], (0.5, 0.9), None).fired is True
    assert trigger_6(False, checks, (0.5, 0.9), None).fired is None


# ---------------------------------------------------------------- params and purity


def test_gate_params_from_registry(registry_root):
    with pytest.raises(UnsetParameter):
        GateParams.from_thresholds(load_thresholds(registry_root))
    path = registry_root / "registry" / "thresholds.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for entry in data["parameters"].values():
        if entry["value"] is None:
            entry["value"] = 3
    write_lf(path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    params = GateParams.from_thresholds(load_thresholds(registry_root))
    assert params.bootstrap_draws == 2000 and params.omega_strata == 5 and params.lag == 2.0


FORBIDDEN = {"os", "pathlib", "time", "datetime", "random", "subprocess", "shutil", "io", "socket"}
ENGINE = [p for d in ("measures", "verdict") for p in (Path(__file__).parents[1] / "src" / "viveka" / d).glob("*.py")]


@pytest.mark.parametrize("module", ENGINE, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_engine_modules_are_pure(module):
    tree = ast.parse(module.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not {a.name.split(".")[0] for a in node.names} & FORBIDDEN, module
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in FORBIDDEN, module
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"open", "print", "input"}, module
