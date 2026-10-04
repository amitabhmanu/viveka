"""A coder run through the Claude Code CLI in headless mode (decision D-4).

One call codes one batch. The call pins its model, has no tools and no MCP servers, loads no user or project
settings, keeps no session, names no fallback model, and runs in an empty directory, so the coder sees its
registered system prompt and the batch's redacted items and nothing of this project. The answer is constrained
to the registered schema by the CLI and validated again here.

The raw output of every call is written to the archive before it is parsed, under the call's request id. A call
that was answered is not made again: an interrupted pass resumes, and a rerun replays, without spending a call.
Only a changed task version, item, coder or repetition makes a new one. A call that failed (the CLI exited with
an error, or reported one: no login, a rate limit, a timeout) is kept beside it as a numbered failure and is not
an answer: its items are missing in that run, and the next run makes the call again.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from viveka.coders.base import (
    CoderSpec,
    Item,
    Label,
    Missing,
    TaskSpec,
    batch_schema,
    batches,
    parse_answer,
    request_id,
    user_message,
)

Runner = Callable[[list[str], str], tuple[int, str, str]]  # (argv, stdin) -> (exit code, stdout, stderr)
CALL_TIMEOUT_SECONDS = 900


class CallCapExceeded(RuntimeError):
    """The registered number of live calls for one run is used up; archived answers still replay."""


def run_in_empty_directory(argv: list[str], stdin: str) -> tuple[int, str, str]:
    with tempfile.TemporaryDirectory(prefix="viveka-coder-") as empty:
        done = subprocess.run(argv, input=stdin, capture_output=True, text=True, encoding="utf-8", cwd=empty,
                              timeout=CALL_TIMEOUT_SECONDS, check=False)
    return done.returncode, done.stdout, done.stderr


def _answered(record: dict) -> bool:
    """Whether the CLI returned an answer at all (which may still be unparseable or invalid, and is then final)."""
    if record.get("exit_code") != 0:
        return False
    try:
        envelope = json.loads(record.get("stdout") or "")
    except json.JSONDecodeError:
        return True  # it answered, in a form that cannot be read: archived as its answer, parsed as missing
    return not (isinstance(envelope, dict) and envelope.get("is_error"))


class ClaudeCliCoder:
    def __init__(self, spec: CoderSpec, archive: Path, *, max_live_calls: int | None = None,
                 runner: Runner = run_in_empty_directory, executable: str = "claude",
                 cli_version: str | None = None):
        self.spec = spec
        self._cli_version = cli_version
        self.archive = archive
        self.max_live_calls = max_live_calls
        self.runner = runner
        self.executable = executable
        self.live_calls = 0
        self.replayed = 0

    @property
    def cli_version(self) -> str:
        """The CLI's own version, recorded with every call: an update can change how a model is driven."""
        if self._cli_version is None:
            try:
                done = subprocess.run([self.executable, "--version"], capture_output=True, text=True, timeout=60,
                                      check=False)
                self._cli_version = done.stdout.strip() or f"unknown (exit {done.returncode})"
            except (OSError, subprocess.TimeoutExpired) as exc:
                self._cli_version = f"unknown ({type(exc).__name__})"
        return self._cli_version

    def argv(self, task: TaskSpec) -> list[str]:
        return [self.executable, "--print", "--model", self.spec.model_id, "--effort", self.spec.effort,
                "--system-prompt", task.system_prompt,
                "--json-schema", json.dumps(batch_schema(task.item_schema), separators=(",", ":")),
                "--output-format", "json", "--tools", "", "--strict-mcp-config", "--setting-sources", "",
                "--no-session-persistence"]

    def code(self, task: TaskSpec, items: Sequence[Item], *, seed: int, rep: int = 0) -> list[Label | Missing]:
        """A label or a missing mark for every item, coded in batches; batch order and membership follow
        (seed, rep) only."""
        out: list[Label | Missing] = []
        for batch in batches(items, task.batch_size, seed, rep):
            rid = request_id(task, [item.item_id for item in batch], self.spec, rep)
            record = self._archived(rid) or self._call(task, batch, rid, rep)
            out += self._parse(record, batch, task, rep, rid)
        return out

    # -- one call ----------------------------------------------------------

    def _path(self, rid: str) -> Path:
        return self.archive / rid[:2] / f"{rid}.json"

    def _archived(self, rid: str) -> dict | None:
        path = self._path(rid)
        if not path.is_file():
            return None
        self.replayed += 1
        return json.loads(path.read_text(encoding="utf-8"))

    def _call(self, task: TaskSpec, batch: Sequence[Item], rid: str, rep: int) -> dict:
        if self.max_live_calls is not None and self.live_calls >= self.max_live_calls:
            raise CallCapExceeded(f"{self.spec.coder_id}: the cap of {self.max_live_calls} live call(s) for this "
                                  "run is reached; rerun to continue from the archive")
        self.live_calls += 1
        try:
            code, stdout, stderr = self.runner(self.argv(task), user_message(batch))
        except (OSError, subprocess.TimeoutExpired) as exc:
            code, stdout, stderr = -1, "", f"{type(exc).__name__}: {exc}"
        record = {"request_id": rid, "task": task.task_id, "task_version": task.version,
                  "coder_id": self.spec.coder_id, "model_id": self.spec.model_id, "effort": self.spec.effort,
                  "cli_version": self.cli_version,
                  "rep": rep, "item_ids": [item.item_id for item in batch], "exit_code": code,
                  "stdout": stdout, "stderr": stderr}
        path = self._path(rid)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not _answered(record):
            attempt = len(list(path.parent.glob(f"{rid}.failed-*.json"))) + 1
            path = path.with_name(f"{rid}.failed-{attempt}.json")
        with open(path, "x", encoding="utf-8", newline="\n") as fh:  # archived verbatim, before any parsing
            fh.write(json.dumps(record, ensure_ascii=False, indent=1) + "\n")
        return record

    def _parse(self, record: dict, batch: Sequence[Item], task: TaskSpec, rep: int, rid: str
               ) -> list[Label | Missing]:
        def missing(reason: str) -> list[Label | Missing]:
            return [Missing(item.item_id, self.spec.coder_id, rep, rid, reason) for item in batch]

        if record.get("exit_code") != 0:
            return missing("call_failed")
        try:
            envelope = json.loads(record.get("stdout") or "")
        except json.JSONDecodeError:
            return missing("unparseable")
        if not isinstance(envelope, dict) or envelope.get("is_error"):
            return missing("call_failed")
        # A label from another model would break the coder's identity: the CLI reports which models answered.
        used = envelope.get("modelUsage")
        if isinstance(used, dict) and used and not any(self.spec.model_id in name or name in self.spec.model_id
                                                       for name in used):
            return missing("wrong_model")
        answer = envelope.get("structured_output")
        if answer is None and isinstance(envelope.get("result"), str):
            try:
                answer = json.loads(envelope["result"])
            except json.JSONDecodeError:
                return missing("unparseable")
        return parse_answer(answer, batch, task, self.spec, rep, rid)
