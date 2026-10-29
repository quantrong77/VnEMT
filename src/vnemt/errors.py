"""Exception hierarchy. User-facing messages are in Vietnamese (SPEC Q-05)."""

from __future__ import annotations


class VnEMTError(Exception):
    """Base class for all VnEMT errors."""


class CaseError(VnEMTError):
    """Invalid case file: YAML syntax, schema violation or inconsistent data."""

    def __init__(self, message: str, path: str | None = None, source: str | None = None) -> None:
        self.path = path
        self.source = source
        prefix = f"{source}: " if source else ""
        where = f"{path}: " if path else ""
        super().__init__(f"{prefix}{where}{message}")


class TopologyError(VnEMTError):
    """Network topology cannot be solved (floating node, source loop...)."""


class SolverError(VnEMTError):
    """Numerical failure inside the EMT core."""
