import json
import re

import jsonschema
import pytest
import yaml
from conftest import HOOKS, REPO

from viveka.cli import main


def test_status_without_frozen_registry(project, capsys):
    assert main(["status", "--root", str(project)]) == 0
    out = capsys.readouterr().out
    assert "no frozen registry" in out
    assert "open decisions: 8" in out


def test_status_with_frozen_registry(project, freeze, capsys):
    freeze(project, ["registry/thresholds.yaml"])
    assert main(["status", "--root", str(project)]) == 0
    assert "frozen version 1 (components: test)" in capsys.readouterr().out


def test_status_on_the_real_repository(capsys):
    assert main(["status", "--root", str(REPO)]) == 0
    assert "Viveka status" in capsys.readouterr().out


def test_session_context_matches_cli(project, hook, capsys):
    main(["status", "--root", str(project)])
    cli_out = capsys.readouterr().out.strip()
    result = hook("session_context.py", project, {"hook_event_name": "SessionStart"})
    assert result.returncode == 0
    assert result.stdout.strip() == cli_out


@pytest.mark.parametrize("name", ["thresholds", "instrument"])
def test_registry_files_match_their_schemas(name):
    schema = json.loads((REPO / "registry" / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))
    data = yaml.safe_load((REPO / "registry" / f"{name}.yaml").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(data)


def test_thresholds_schema_rejects_missing_parameter_and_bad_share():
    schema = json.loads((REPO / "registry" / "schemas" / "thresholds.schema.json").read_text(encoding="utf-8"))
    data = yaml.safe_load((REPO / "registry" / "thresholds.yaml").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)

    missing = json.loads(json.dumps(data))
    del missing["parameters"]["delta"]
    assert not validator.is_valid(missing)

    bad_share = json.loads(json.dumps(data))
    bad_share["parameters"]["r_min_coverage"]["value"] = 1.5
    assert not validator.is_valid(bad_share)


def _hook_scripts(text: str) -> set[str]:
    return set(re.findall(r"\.claude/hooks/([A-Za-z_]+\.py)", text))


def test_every_configured_hook_script_exists():
    settings = (REPO / ".claude" / "settings.json").read_text(encoding="utf-8")
    json.loads(settings)
    agents = "".join(p.read_text(encoding="utf-8") for p in (REPO / ".claude" / "agents").glob("*.md"))
    scripts = _hook_scripts(settings) | _hook_scripts(agents)
    assert scripts, "no hook scripts configured"
    for script in scripts:
        assert (HOOKS / script).is_file(), script
