"""Structural non-secret connection target contracts for provider transports."""

from __future__ import annotations

from typing import Protocol


class ConnectionTarget(Protocol):
    """Minimum non-secret endpoint identity shared by provider transports."""

    name: str
    host: str
    port: int
    expected_hostname: str


class ReadOnlyConnectionTarget(ConnectionTarget, Protocol):
    """Minimum non-secret connection identity required for state collection."""

    protected_interfaces: tuple[str, ...]
