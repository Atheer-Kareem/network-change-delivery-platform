"""Environment-only secret loading behind a replaceable boundary."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

USERNAME_VARIABLE = "NCDP_DEVICE_USERNAME"
PASSWORD_VARIABLE = "NCDP_DEVICE_PASSWORD"


class SecretError(ValueError):
    """Raised without exposing secret values."""


@dataclass(frozen=True, repr=False)
class DeviceCredentials:
    """Ephemeral credentials that must never enter evidence or plans."""

    username: str
    password: str


class SecretProvider(Protocol):
    """Boundary for obtaining device credentials."""

    def load(self) -> DeviceCredentials:
        """Load ephemeral credentials or fail with variable names only."""


class EnvironmentSecretProvider:
    """Temporary environment-backed secret provider."""

    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self._environment = environment if environment is not None else os.environ

    def load(self) -> DeviceCredentials:
        """Load both required variables without logging values."""
        missing = [
            name
            for name in (USERNAME_VARIABLE, PASSWORD_VARIABLE)
            if not self._environment.get(name)
        ]
        if missing:
            raise SecretError(
                f"missing required environment variables: {', '.join(missing)}"
            )
        return DeviceCredentials(
            username=self._environment[USERNAME_VARIABLE],
            password=self._environment[PASSWORD_VARIABLE],
        )
