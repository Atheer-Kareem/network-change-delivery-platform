"""Structural target boundary shared only by read-only provider collection."""

from __future__ import annotations

from typing import Protocol


class ReadOnlyConnectionTarget(Protocol):
    """Minimum non-secret connection identity required for state collection."""

    name: str
    host: str
    port: int
    expected_hostname: str
    protected_interfaces: tuple[str, ...]
