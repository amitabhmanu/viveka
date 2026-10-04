"""The coder adapter: batching, request identity, the local archive, and parsing that never guesses."""

from __future__ import annotations

import json

import pytest

from viveka.coders.base import CoderSpec, Item, Label, Missing, TaskSpec, batch_schema, batches, request_id
from viveka.coders.claude_cli import CallCapExceeded, ClaudeCliCoder

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["label"],
          "properties": {"label": {"enum": ["+", "-", "x", "none"]}, "reason_span": {"type": ["string", "null"]}}}
TASK = TaskSpec("T1", "v1", "Code each citation context.", SCHEMA, batch_size=3)
OPUS = CoderSpec("claude-cli:claude-opus-5-5", "claude-opus-5-5", "claude-opus-5-5", "high")
ITEMS = [Item(f"k{i}", f"context {i}") for i in range(7)]
VERSION = "9.9.9 (test)"


def make(archive, **options):
    return ClaudeCliCoder(OPUS, archive, cli_version=VERSION, **options)


class FakeCli:
    """Answers every item '+', and records what it was called with."""

    def __init__(self, answer=None, exit_code=0, model="claude-opus-5-5"):
        self.calls, self.answer, self.exit_code, self.model = [], answer, exit_code, model

    def __call__(self, argv, stdin):
        self.calls.append((argv, stdin))
        n = stdin.count("<item key=")
        answer = self.answer if self.answer is not None else {
            "labels": [{"key": str(i + 1), "label": "+", "reason_span": None} for i in range(n)]}
        envelope = {"type": "result", "is_error": False, "structured_output": answer,
                    "modelUsage": {self.model: {"inputTokens": 1}}}
        return self.exit_code, json.dumps(envelope), ""


def test_batches_follow_the_seed_and_repetition_and_not_the_order_items_arrive_in():
    first = batches(ITEMS, 3, seed=7, rep=0)
    assert [len(b) for b in first] == [3, 3, 1]
    assert batches(list(reversed(ITEMS)), 3, seed=7, rep=0) == first
    assert batches(ITEMS, 3, seed=7, rep=1) != first  # a retest codes each item beside other items
    assert sorted(i.item_id for b in first for i in b) == sorted(i.item_id for i in ITEMS)
    with pytest.raises(ValueError):
        batches([Item("a", "x"), Item("a", "y")], 3, seed=7, rep=0)


def test_a_request_is_identified_by_task_version_items_coder_and_repetition():
    ids = ["k1", "k2"]
    base = request_id(TASK, ids, OPUS, 0)
    assert request_id(TASK, ids, OPUS, 0) == base
    changed = [request_id(TaskSpec("T1", "v2", TASK.system_prompt, SCHEMA, 3), ids, OPUS, 0),
               request_id(TASK, ["k2", "k1"], OPUS, 0), request_id(TASK, ids, OPUS, 1),
               request_id(TASK, ids, CoderSpec("c", "f", "claude-sonnet-5-5", "high"), 0)]
    assert len({base, *changed}) == 5


def test_one_call_per_batch_with_a_pinned_model_no_tools_and_no_project_in_sight(tmp_path):
    cli = FakeCli()
    coder = make(tmp_path / "archive", runner=cli)
    labels = coder.code(TASK, ITEMS, seed=7)
    assert len(cli.calls) == 3 and coder.live_calls == 3  # seven items in batches of three
    assert all(isinstance(x, Label) and x.value == {"label": "+", "reason_span": None} for x in labels)
    assert sorted(x.item_id for x in labels) == sorted(i.item_id for i in ITEMS)
    argv, stdin = cli.calls[0]
    assert argv[argv.index("--model") + 1] == "claude-opus-5-5" and argv[argv.index("--tools") + 1] == ""
    assert "--fallback-model" not in argv and "--no-session-persistence" in argv and "--strict-mcp-config" in argv
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert json.loads(argv[argv.index("--json-schema") + 1]) == batch_schema(SCHEMA)
    assert "k0" not in stdin and "k1" not in stdin  # items are keyed by position; their ids are never shown


def test_archived_answers_replay_without_a_call_and_the_cap_counts_only_live_calls(tmp_path):
    archive = tmp_path / "archive"
    first = make(archive, runner=FakeCli()).code(TASK, ITEMS, seed=7)
    cli = FakeCli()
    again = make(archive, runner=cli, max_live_calls=0)
    assert again.code(TASK, ITEMS, seed=7) == first and cli.calls == [] and again.replayed == 3
    capped = make(tmp_path / "other", runner=FakeCli(), max_live_calls=2)
    with pytest.raises(CallCapExceeded):
        capped.code(TASK, ITEMS, seed=7)
    assert capped.live_calls == 2
    resumed = make(tmp_path / "other", runner=FakeCli(), max_live_calls=1)
    assert len(resumed.code(TASK, ITEMS, seed=7)) == 7 and (resumed.live_calls, resumed.replayed) == (1, 2)


def test_the_raw_output_is_archived_before_parsing_even_when_it_cannot_be_parsed(tmp_path):
    def broken(argv, stdin):
        return 0, "not json at all", "warning"

    coder = make(tmp_path / "archive", runner=broken)
    out = coder.code(TASK, ITEMS[:2], seed=7)
    assert all(isinstance(x, Missing) and x.reason == "unparseable" for x in out)
    (stored,) = (tmp_path / "archive").rglob("*.json")
    record = json.loads(stored.read_text(encoding="utf-8"))
    assert record["cli_version"] == VERSION and record["stdout"] == "not json at all"
    assert record["stderr"] == "warning" and len(record["item_ids"]) == 2


def test_a_missing_repeated_or_invalid_label_is_missing_and_is_never_filled_in(tmp_path):
    answer = {"labels": [{"key": "1", "label": "+"}, {"key": "2", "label": "maybe"},
                         {"key": "3", "label": "x", "reason_span": "poor blinding"},
                         {"key": "3", "label": "+"}]}
    coder = make(tmp_path / "archive", runner=FakeCli(answer))
    out = coder.code(TaskSpec("T1", "v1", "p", SCHEMA, batch_size=4), ITEMS[:4], seed=7)
    assert isinstance(out[0], Label) and out[0].value == {"label": "+"}
    assert [type(x).__name__ + ":" + getattr(x, "reason", "") for x in out[1:]] == [
        "Missing:invalid", "Missing:absent", "Missing:absent"]  # key 3 came twice; key 4 never came


def test_a_failed_call_is_kept_as_a_failure_and_made_again_on_the_next_run(tmp_path):
    def not_logged_in(argv, stdin):
        return 1, json.dumps({"type": "result", "is_error": True, "result": "Failed to authenticate"}), ""

    archive = tmp_path / "archive"
    first = make(archive, runner=not_logged_in)
    assert {x.reason for x in first.code(TASK, ITEMS[:2], seed=7)} == {"call_failed"}
    again = make(archive, runner=not_logged_in)
    again.code(TASK, ITEMS[:2], seed=7)
    assert (again.live_calls, again.replayed) == (1, 0)  # the failure was not replayed as if it were an answer
    assert sorted(p.name.split(".", 1)[1] for p in archive.rglob("*.json")) == ["failed-1.json", "failed-2.json"]
    fixed = make(archive, runner=FakeCli())
    assert all(isinstance(x, Label) for x in fixed.code(TASK, ITEMS[:2], seed=7))
    replay = make(archive, runner=FakeCli(), max_live_calls=0)
    assert all(isinstance(x, Label) for x in replay.code(TASK, ITEMS[:2], seed=7)) and replay.replayed == 1


def test_a_failed_call_or_an_answer_from_another_model_yields_no_labels(tmp_path):
    failed = make(tmp_path / "a", runner=FakeCli(exit_code=1)).code(TASK, ITEMS[:2], seed=7)
    assert {x.reason for x in failed} == {"call_failed"}
    other = make(tmp_path / "b", runner=FakeCli(model="claude-haiku-4-5-20251001"))
    assert {x.reason for x in other.code(TASK, ITEMS[:2], seed=7)} == {"wrong_model"}
