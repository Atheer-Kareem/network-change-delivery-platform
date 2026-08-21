"""Temporary replaceable local inventory boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import yaml

from network_change_delivery.models import InventoryDevice, InventoryDocument


class InventoryError(ValueError):
    """Raised when local inventory cannot resolve a safe target."""


class InventoryProvider(Protocol):
    """Boundary for target inventory resolution."""

    def resolve(self, target: str) -> InventoryDevice:
        """Resolve one explicit logical target."""


class LocalYamlInventoryProvider:
    """Temporary YAML-backed inventory implementation."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def resolve(self, target: str) -> InventoryDevice:
        """Resolve exactly one named device or fail closed."""
        try:
            payload = yaml.safe_load(self._path.read_text(encoding="utf-8"))
            document = InventoryDocument.model_validate(payload)
        except (OSError, yaml.YAMLError, ValueError) as error:
            raise InventoryError("local inventory is invalid or unreadable") from error
        matches = [device for device in document.devices if device.name == target]
        if len(matches) != 1:
            raise InventoryError(f"target {target!r} does not resolve exactly once")
        return matches[0]
