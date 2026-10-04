"""What every coder shares: tasks, items, batches, request identity and parsing.

Calls are the scarce resource (decision D-6: coders run on the owner's plan, not metered billing), so items are
coded in batches, one call per batch. A batch is drawn by a seeded shuffle of all the items of a pass, so its
composition does not follow field, commitment or date, and it differs between repetitions: the test-retest audit
therefore also measures whether an item's label depends on the items it was coded beside.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import jsonschema


@dataclass(frozen=True)
class TaskSpec:
    task_id: str  # "T1" ... "T6"
    version: str  # hash of the registered prompt and schema: a codebook change is a new task version
    system_prompt: str
    item_schema: Mapping  # JSON Schema of one item's label (an object)
    batch_size: int


@dataclass(frozen=True)
class Item:
    item_id: str  # opaque: carries no field, case or author
    text: str  # redacted


@dataclass(frozen=True)
class CoderSpec:
    coder_id: str  # e.g. "claude-cli:claude-opus-5-5"
    family: str  # the unit intervals resample over (decision D-21: one per model)
    model_id: str
    effort: str


@dataclass(frozen=True)
class Label:
    item_id: str
    coder_id: str
    rep: int
    request_id: str
    value: Mapping


@dataclass(frozen=True)
class Missing:
    item_id: str
    coder_id: str
    rep: int
    request_id: str
    reason: str  # "call_failed", "unparseable", "wrong_model", "absent", "invalid"


def request_id(task: TaskSpec, item_ids: Sequence[str], coder: CoderSpec, rep: int) -> str:
    """Identity of one call: the same task version, items in the same order, coder and repetition."""
    payload = json.dumps([task.task_id, task.version, list(item_ids), coder.coder_id, coder.model_id, coder.effort,
                          rep], separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def batches(items: Sequence[Item], size: int, seed: int, rep: int) -> list[list[Item]]:
    """The items of a pass in batches of `size`, shuffled by (seed, rep); the same for every coder."""
    if size < 1:
        raise ValueError("a batch holds at least one item")
    ordered = sorted(items, key=lambda item: item.item_id)
    if len({item.item_id for item in ordered}) != len(ordered):
        raise ValueError("item ids must be unique within a pass")
    random.Random(f"{seed}:{rep}").shuffle(ordered)
    return [ordered[i:i + size] for i in range(0, len(ordered), size)]


def batch_schema(item_schema: Mapping) -> dict:
    """The schema of one call's answer: a label per item, keyed by the item's position in the batch."""
    properties = {"key": {"type": "string"}, **dict(item_schema.get("properties") or {})}
    required = ["key", *(item_schema.get("required") or [])]
    return {"type": "object", "additionalProperties": False, "required": ["labels"],
            "properties": {"labels": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "properties": properties, "required": required}}}}


def user_message(batch: Sequence[Item]) -> str:
    """The only varying content a coder sees. Items are keyed by position, so not even their ids are shown."""
    parts = [f"There are {len(batch)} items. Code each one on its own; give one label per item, with its key."]
    parts += [f"<item key=\"{index + 1}\">\n{item.text}\n</item>" for index, item in enumerate(batch)]
    return "\n\n".join(parts)


def parse_answer(answer: object, batch: Sequence[Item], task: TaskSpec, coder: CoderSpec, rep: int,
                 rid: str) -> list[Label | Missing]:
    """One result per item of the batch, in batch order. An item the answer omits, repeats or mislabels against
    the registered schema is missing; nothing is inferred from its neighbours."""
    rows = answer.get("labels") if isinstance(answer, Mapping) else None
    if not isinstance(rows, list):
        return [Missing(item.item_id, coder.coder_id, rep, rid, "unparseable") for item in batch]
    by_key: dict[str, list[Mapping]] = {}
    for row in rows:
        if isinstance(row, Mapping) and isinstance(row.get("key"), str):
            by_key.setdefault(row["key"].strip(), []).append(row)
    validator = jsonschema.Draft202012Validator(dict(task.item_schema))
    out: list[Label | Missing] = []
    for index, item in enumerate(batch):
        found = by_key.get(str(index + 1), [])
        if len(found) != 1:
            out.append(Missing(item.item_id, coder.coder_id, rep, rid, "absent"))
            continue
        value = {k: v for k, v in found[0].items() if k != "key"}
        if validator.is_valid(value):
            out.append(Label(item.item_id, coder.coder_id, rep, rid, value))
        else:
            out.append(Missing(item.item_id, coder.coder_id, rep, rid, "invalid"))
    return out
