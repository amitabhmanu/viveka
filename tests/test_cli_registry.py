import pytest
from conftest import write_lf

from viveka import provenance
from viveka.cli import main


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_validate_freeze_verify_bump_cycle(registry_root, capsys):
    root = str(registry_root)
    assert run(capsys, "registry", "validate", "--root", root)[0] == 0
    assert run(capsys, "registry", "verify", "--root", root)[1].strip() == "no frozen components"

    code, out, _ = run(capsys, "registry", "freeze", "schemas", "--reason", "cli test", "--no-git", "--root", root)
    assert code == 0 and "froze registry version 1" in out and "no git" in out
    assert "1 frozen component(s) verify" in run(capsys, "registry", "verify", "--root", root)[1]
    assert "version 1; frozen: schemas (all verify)" in run(capsys, "status", "--root", root)[1]

    write_lf(registry_root / "registry" / "schemas" / "instrument.schema.json", "{}")
    code, out, _ = run(capsys, "registry", "verify", "--root", root)
    assert code == 1 and "changed registry/schemas/instrument.schema.json" in out

    code, _, err = run(capsys, "registry", "bump", "schemas", "--reason", "x", "--prompted-by", "y", "--root", root)
    assert code == 1 and "restore it from tag" in err

    assert run(capsys, "registry", "verify", "codebook", "--root", root)[0] == 1
    assert run(capsys, "ledger", "verify", "--root", root)[0] == 0


def test_freeze_refusal_exits_1_with_reasons(registry_root, capsys):
    code, _, err = run(capsys, "registry", "freeze", "fitted", "--reason", "too early", "--no-git",
                       "--root", str(registry_root))
    assert code == 1 and "n_min_disconfirmations has no value" in err


def test_bump_requires_prompted_by(registry_root, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["registry", "bump", "schemas", "--reason", "x", "--root", str(registry_root)])
    assert exc.value.code == 2


def test_verify_run(registry_root, capsys):
    with provenance.RunContext(registry_root, "S0", "cli", "dev", []) as ctx:
        ctx.store(b"x", "txt")
    assert run(capsys, "verify", ctx.run_id, "--root", str(registry_root))[0] == 0
    assert run(capsys, "verify", "2026-01-01T0000Z-none-none-0000", "--root", str(registry_root))[0] == 1
