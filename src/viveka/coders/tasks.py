"""Registered coding tasks: a prompt in registry/prompts/ with YAML front matter, the codebook section it embeds
verbatim, and the label schema beside it (decision D-23).

The task version is a hash of exactly what a coder receives as instructions (the rendered prompt) and of the
schema its answer must meet, so any change to the codebook, the prompt or the schema is a new task version, and
archived answers to the old version are never replayed for the new one.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from viveka.coders.base import TaskSpec

PROMPTS = Path("registry") / "prompts"
CODEBOOK = Path("registry") / "codebook"
PLACEHOLDER = "{{codebook}}"


class TaskError(ValueError):
    pass


def load_task(root: Path, name: str) -> TaskSpec:
    """The task registered as registry/prompts/<name>.md, rendered with its codebook section."""
    path = root / PROMPTS / f"{name}.md"
    if not path.is_file():
        raise TaskError(f"no registered task prompt {path.relative_to(root).as_posix()}")
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise TaskError(f"{name}: the prompt must begin with YAML front matter")
    front, body = text[4:].split("\n---\n", 1)
    meta = yaml.safe_load(front) or {}
    for key in ("task", "schema", "batch_size"):
        if key not in meta:
            raise TaskError(f"{name}: front matter has no {key!r}")
    if PLACEHOLDER in body:
        book = meta.get("codebook")
        if not book:
            raise TaskError(f"{name}: the prompt embeds a codebook section but names none")
        body = body.replace(PLACEHOLDER, (root / CODEBOOK / book).read_text(encoding="utf-8").replace("\r\n", "\n"))
    schema = json.loads((root / PROMPTS / f"{meta['schema']}.schema.json").read_text(encoding="utf-8"))
    prompt = body.strip() + "\n"
    digest = hashlib.sha256((prompt + json.dumps(schema, sort_keys=True, separators=(",", ":"))).encode("utf-8"))
    return TaskSpec(str(meta["task"]), digest.hexdigest()[:16], prompt, schema, int(meta["batch_size"]))
