"""Dated sub-windows, their stability variants, and trajectory closure ("Dating the verdict")."""

from __future__ import annotations

from collections.abc import Sequence


def subwindows(start: int, end: int, length: int) -> list[tuple[int, int]]:
    """Inclusive year windows of ``length`` years stepped yearly across [start, end]; empty if too short."""
    if length < 1 or end - start + 1 < length:
        return []
    return [(y, y + length - 1) for y in range(start, end - length + 2)]


def window_variants(start: int, end: int, length_range: tuple[int, int], shift_max: int) -> list[
    tuple[int, int, list[tuple[int, int]]]
]:
    """Every (length, boundary shift, windows) variant used by the stability gate."""
    variants = []
    for length in range(length_range[0], length_range[1] + 1):
        for shift in range(0, shift_max + 1):
            variants.append((length, shift, subwindows(start + shift, end, length)))
    return variants


def trajectory_closed(counts_by_window: Sequence[int], v: int, index: int) -> bool:
    """True when the lineage engaged the claim (>= v) before ``index`` and stays below v from ``index`` on."""
    if not 0 <= index < len(counts_by_window):
        raise IndexError("window index out of range")
    engaged_before = any(c >= v for c in counts_by_window[:index])
    return engaged_before and all(c < v for c in counts_by_window[index:])
