"""Content hashes used by the registry, the ledger and run manifests.

A file hash is SHA-256 of the file's raw bytes (line endings are pinned to LF by
.gitattributes, so every checkout hashes the same). A tree hash is SHA-256 over
sorted ``<posix path>\\0<file hash>\\n`` lines, so adding, removing, renaming or
changing any byte of any file changes it, and no timestamp ever enters it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

PREFIX = "sha256:"
_CHUNK = 1 << 20


def sha256_bytes(data: bytes) -> str:
    return PREFIX + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return PREFIX + digest.hexdigest()


def tree_hash(file_hashes: dict[str, str]) -> str:
    """Order-independent hash of a mapping from POSIX path to file hash."""
    lines = "".join(f"{path}\0{sha}\n" for path, sha in sorted(file_hashes.items()))
    return sha256_bytes(lines.encode("utf-8"))
