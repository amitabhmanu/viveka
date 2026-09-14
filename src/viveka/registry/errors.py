"""Registry exceptions. Each carries a message fit to show a user as-is."""

from __future__ import annotations


class RegistryError(Exception):
    """Base class for registry problems."""


class UnknownComponent(RegistryError):
    """A component name that the component map does not define."""


class ValidationFailed(RegistryError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("registry validation failed:\n" + "\n".join(f"  - {p}" for p in problems))


class FreezeRefused(RegistryError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("freeze refused:\n" + "\n".join(f"  - {p}" for p in problems))


class RegistryNotFrozen(RegistryError):
    def __init__(self, components: list[str]):
        self.components = components
        super().__init__("registry components are not frozen: " + ", ".join(components))


class RegistryIntegrityError(RegistryError):
    def __init__(self, mismatches: dict[str, list[str]]):
        self.mismatches = mismatches
        lines = [f"  - {name}: {'; '.join(issues)}" for name, issues in sorted(mismatches.items())]
        super().__init__("frozen registry components no longer match FROZEN.json:\n" + "\n".join(lines))


class MissingParameter(RegistryError):
    """thresholds.yaml lacks a parameter that the code uses."""


class UnsetParameter(RegistryError):
    """Code read a parameter whose value is still null."""
