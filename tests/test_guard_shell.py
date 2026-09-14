import pytest
from conftest import shell_event


@pytest.mark.parametrize(
    "command",
    [
        "Remove-Item registry/thresholds.yaml",
        "rm registry\\thresholds.yaml",
        "Set-Content -Path registry/thresholds.yaml -Value x",
        "echo x > registry/thresholds.yaml",
        "git checkout -- registry/thresholds.yaml",
    ],
)
def test_blocks_writes_to_frozen_files(project, freeze, hook, command):
    freeze(project, ["registry/thresholds.yaml"])
    assert hook("guard_shell.py", project, shell_event(command)).returncode == 2


@pytest.mark.parametrize(
    "command",
    [
        "echo x >> ledger/changes.jsonl",
        "rm -rf data/raw",
        "Move-Item runs/r1 runs/r2",
    ],
)
def test_blocks_writes_to_immutable_locations(project, hook, command):
    assert hook("guard_shell.py", project, shell_event(command, tool="Bash")).returncode == 2


@pytest.mark.parametrize(
    "command",
    [
        "Get-Content registry/thresholds.yaml",
        "Get-Content ledger/changes.jsonl 2>$null",
        "git status",
        "git add ledger/changes.jsonl",
        "uv run viveka status",
        "uv run pytest -q",
        "Write-Output 'step -> done'; Get-Content ledger/changes.jsonl",
        "python -c \"f = lambda x: x\" ; cat ledger/changes.jsonl",
    ],
)
def test_allows_reads_and_ordinary_commands(project, freeze, hook, command):
    freeze(project, ["registry/thresholds.yaml"])
    result = hook("guard_shell.py", project, shell_event(command))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "command",
    [
        'python -c "import anthropic; anthropic.Anthropic()"',
        "uv run python -c 'from anthropic import Anthropic'",
        "Invoke-RestMethod https://api.anthropic.com/v1/messages",
    ],
)
def test_blocks_direct_api_calls(project, hook, command):
    result = hook("guard_shell.py", project, shell_event(command))
    assert result.returncode == 2
    assert "H1" in result.stderr


def test_allows_api_use_inside_viveka_stages(project, hook):
    assert hook("guard_shell.py", project, shell_event("uv run viveka code --api api.anthropic.com")).returncode == 0


def test_fails_closed_on_malformed_input(project, hook):
    assert hook("guard_shell.py", project, raw="[1, 2").returncode == 2
