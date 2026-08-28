"""Entry point for the future externally installed protected staging controller."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from network_change_delivery.buildkite_staging import (
    BuildkiteStagingContext,
    staging_context_from_environment,
)
from network_change_delivery.protected_staging import (
    ProtectedStagingError,
    ProtectedStagingManifest,
    validate_protected_bundle,
    validate_state_root,
)

PROTECTED_CONTROLLER_CONFIG = (
    Path.home() / ".config/buildkite/ncdp-staging/protected-controller.json"
)


class ProtectedControllerConfig(BaseModel):
    """Agent-owned locations; none may be supplied through checkout arguments."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1
    bundle_root: Path
    manifest_path: Path
    state_root: Path
    netbox_url: str
    netbox_token_file: Path
    openbao_url: str
    cml_username_file: Path
    cml_password_file: Path
    cml_ca_file: Path


class ProtectedStagingController:
    """Validate installed authority before any privileged integration is reached."""

    def __init__(
        self,
        config: ProtectedControllerConfig,
        manifest: ProtectedStagingManifest,
        context: BuildkiteStagingContext,
        checkout: Path,
    ) -> None:
        self.config = config
        self.manifest = manifest
        self.context = context
        self.checkout = checkout

    @classmethod
    def load(
        cls,
        *,
        config_path: Path = PROTECTED_CONTROLLER_CONFIG,
        checkout: Path,
    ) -> ProtectedStagingController:
        if config_path != PROTECTED_CONTROLLER_CONFIG:
            raise ProtectedStagingError("protected controller config path rejected")
        try:
            config = ProtectedControllerConfig.model_validate_json(
                config_path.read_text(encoding="utf-8")
            )
            manifest = ProtectedStagingManifest.model_validate_json(
                config.manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            raise ProtectedStagingError(
                "protected controller authority invalid"
            ) from None
        validate_protected_bundle(config.bundle_root, checkout, manifest)
        validate_state_root(config.state_root, checkout)
        context = staging_context_from_environment()
        if context.commit != manifest.source_commit:
            raise ProtectedStagingError("Buildkite commit is not installed authority")
        return cls(config, manifest, context, checkout)

    def admit(self) -> dict[str, object]:
        """Return only non-secret authority facts; B3-2B installs and admits I/O."""
        return {
            "schema_version": 1,
            "run_id": self.context.staging_run_id,
            "source_commit": self.manifest.source_commit,
            "bundle_digest": self.manifest.bundle_digest,
            "staging_device_ids": [6, 7],
            "live_deny_device_ids": [1, 2, 3],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("run",))
    arguments = parser.parse_args()
    del arguments
    try:
        controller = ProtectedStagingController.load(checkout=Path.cwd())
        print(json.dumps(controller.admit(), sort_keys=True))
    except ProtectedStagingError as error:
        print(f"protected staging rejected: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
