"""Entry point for the future externally installed protected staging controller."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from network_change_delivery.buildkite_staging import (
    BuildkiteStagingContext,
    staging_context_from_environment,
)
from network_change_delivery.protected_staging import (
    ProtectedCMLClient,
    ProtectedCMLCredentials,
    ProtectedStagingError,
    ProtectedStagingInventoryResolver,
    ProtectedStagingManifest,
    ProtectedTerraformExecutor,
    SubprocessTerraformRunner,
    request_staging_oidc_jwt,
    validate_protected_bundle,
    validate_state_root,
)
from network_change_delivery.protected_staging_runtime import (
    LifecycleIdentity,
    ProtectedCommandRunner,
    ProtectedLifecycleOperations,
    ProtectedNCDPReadOnlyValidator,
    ProtectedReadinessProbe,
    ProtectedRecoveryOperations,
    ProtectedRuntimeEvidence,
    ProtectedRuntimeOperations,
    ProtectedSSHHostTrust,
    ProtectedToolAuthority,
    build_cml_ssl_context,
    build_protected_terraform_environment,
    derive_junos_password_verifier,
    derive_run_directory,
    load_protected_staging_credentials,
    read_protected_file,
    recover_protected_run,
    run_protected_lifecycle,
    terraform_version_runner,
    validate_protected_directory,
    validate_protected_executable,
    verify_ca_digest,
)

PROTECTED_CONTROLLER_CONFIG = (
    Path.home() / ".config/buildkite/ncdp-staging/protected-controller.json"
)


class ProtectedControllerConfig(BaseModel):
    """Agent-owned locations; none may be supplied through checkout arguments."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[2] = 2
    bundle_root: Path
    manifest_path: Path
    state_root: Path
    netbox_token_file: Path
    cml_username_file: Path
    cml_password_file: Path
    cml_ca_file: Path
    tools: ProtectedToolAuthority


class ProtectedStagingController:
    """Validate installed authority before any privileged integration is reached."""

    def __init__(
        self,
        config: ProtectedControllerConfig,
        manifest: ProtectedStagingManifest,
        context: BuildkiteStagingContext | None,
        checkout: Path,
        netbox_token: bytes,
        cml_username: bytes,
        cml_password: bytes,
        cml_ca: bytes,
    ) -> None:
        self.config = config
        self.manifest = manifest
        self.context = context
        self.checkout = checkout
        self._netbox_token = netbox_token
        self._cml_username = cml_username
        self._cml_password = cml_password
        self._cml_ca = cml_ca

    @classmethod
    def load(
        cls,
        *,
        config_path: Path = PROTECTED_CONTROLLER_CONFIG,
        checkout: Path,
        recovery: bool = False,
    ) -> ProtectedStagingController:
        if config_path != PROTECTED_CONTROLLER_CONFIG:
            raise ProtectedStagingError("protected controller config path rejected")
        try:
            config = ProtectedControllerConfig.model_validate_json(
                read_protected_file(config_path, checkout).decode()
            )
            manifest = ProtectedStagingManifest.model_validate_json(
                read_protected_file(config.manifest_path, checkout).decode()
            )
        except (OSError, ValueError):
            raise ProtectedStagingError(
                "protected controller authority invalid"
            ) from None
        validate_protected_bundle(config.bundle_root, checkout, manifest)
        validate_state_root(config.state_root, checkout)
        netbox_token = read_protected_file(config.netbox_token_file, checkout)
        cml_username = read_protected_file(config.cml_username_file, checkout)
        cml_password = read_protected_file(config.cml_password_file, checkout)
        cml_ca = read_protected_file(config.cml_ca_file, checkout)
        verify_ca_digest(cml_ca, manifest)
        validate_protected_executable(config.tools.buildkite_agent, checkout)
        validate_protected_executable(
            config.tools.terraform,
            checkout,
            expected_version=config.tools.terraform_version,
            version_runner=terraform_version_runner,
        )
        validate_protected_executable(config.tools.openssl, checkout)
        validate_protected_executable(config.tools.ssh_keyscan, checkout)
        validate_protected_executable(config.tools.ssh_keygen, checkout)
        validate_protected_directory(config.tools.ansible_collections_root, checkout)
        context = None if recovery else staging_context_from_environment()
        if context is not None:
            if context.commit != manifest.source_commit:
                raise ProtectedStagingError(
                    "Buildkite commit is not installed authority"
                )
            if UUID(context.pipeline_id) != manifest.buildkite_pipeline_id:
                raise ProtectedStagingError(
                    "Buildkite pipeline is not installed authority"
                )
        return cls(
            config,
            manifest,
            context,
            checkout,
            netbox_token,
            cml_username,
            cml_password,
            cml_ca,
        )

    def admit(self) -> dict[str, object]:
        """Return only non-secret authority facts; B3-2B installs and admits I/O."""
        if self.context is None:
            raise ProtectedStagingError("normal staging context missing")
        return {
            "schema_version": 2,
            "run_id": self.context.staging_run_id,
            "source_commit": self.manifest.source_commit,
            "bundle_digest": self.manifest.bundle_digest,
            "staging_device_ids": [6, 7],
            "live_deny_device_ids": [1, 2, 3],
        }

    def run(
        self,
        operations: ProtectedLifecycleOperations,
        run_directory: Path | None = None,
    ) -> ProtectedRuntimeEvidence:
        """Execute the complete admitted lifecycle through protected ports."""
        if self.context is None:
            raise ProtectedStagingError("normal staging context missing")
        if run_directory is None:
            _run_id, run_directory = derive_run_directory(
                self.config.state_root, UUID(self.context.build_id)
            )
        identity = LifecycleIdentity(
            pipeline_id=UUID(self.context.pipeline_id),
            build_id=UUID(self.context.build_id),
            job_id=UUID(self.context.job_id),
            source_commit=self.manifest.source_commit,
            bundle_digest=self.manifest.bundle_digest,
            manifest_digest=self.manifest.digest,
        )
        return run_protected_lifecycle(identity, run_directory, operations)

    def compose(self) -> tuple[ProtectedRuntimeOperations, Path]:
        """Compose concrete integrations solely from admitted protected authority."""
        if self.context is None:
            raise ProtectedStagingError("normal staging context missing")
        command_runner = ProtectedCommandRunner()
        jwt = request_staging_oidc_jwt(
            command_runner, self.config.tools.buildkite_agent
        )
        try:
            token = self._netbox_token.decode("utf-8").strip()
            username = self._cml_username.decode("utf-8").strip()
            password = self._cml_password.decode("utf-8").strip()
            ca_pem = self._cml_ca.decode("ascii")
        except UnicodeDecodeError:
            raise ProtectedStagingError(
                "protected credential encoding rejected"
            ) from None
        resolver = ProtectedStagingInventoryResolver(self.manifest, token)
        targets = resolver.resolve()
        credentials = load_protected_staging_credentials(
            jwt, self.context, self.manifest, targets
        )
        junos = credentials["stg-edge-junos-01"]
        verifier = derive_junos_password_verifier(
            self.config.tools.openssl, junos.password, command_runner
        )
        ssl_context = build_cml_ssl_context(self._cml_ca, self.manifest)
        cml = ProtectedCMLClient(
            self.manifest.cml,
            ProtectedCMLCredentials(username, password),
            ssl_context=ssl_context,
        )
        cml.authenticate()
        _run_id, run_directory = derive_run_directory(
            self.config.state_root, UUID(self.context.build_id)
        )
        variables = {
            "TF_VAR_staging_run_id": self.context.staging_run_id,
            "TF_VAR_lifecycle_state": "DEFINED_ON_CORE",
            "TF_VAR_cisco_bootstrap_hostname": "stg-core-02",
            "TF_VAR_cisco_bootstrap_management_cidr": "192.168.4.30/24",
            "TF_VAR_cisco_bootstrap_username": credentials["stg-core-02"].username,
            "TF_VAR_cisco_bootstrap_password": credentials["stg-core-02"].password,
            "TF_VAR_junos_bootstrap_hostname": "stg-edge-junos-01",
            "TF_VAR_junos_bootstrap_management_cidr": "192.168.4.31/24",
            "TF_VAR_junos_bootstrap_username": junos.username,
            "TF_VAR_junos_bootstrap_password_hash": verifier,
        }
        trusted_path = ":".join(
            sorted(
                {
                    str(self.config.tools.terraform.parent),
                    str(self.config.tools.openssl.parent),
                    str(self.config.tools.ssh_keyscan.parent),
                    str(self.config.tools.ssh_keygen.parent),
                }
            )
        )
        environment = build_protected_terraform_environment(
            terraform_data_dir=run_directory / "terraform-data",
            cml_address=self.manifest.cml.controller_url,
            cml_token=cml.bearer,
            cml_ca_pem=ca_pem,
            variables=variables,
            trusted_path=trusted_path,
        )
        terraform = ProtectedTerraformExecutor(
            self.config.bundle_root,
            run_directory,
            SubprocessTerraformRunner(self.config.tools.terraform),
            environment,
        )
        operations = ProtectedRuntimeOperations(
            manifest=self.manifest,
            run_id=self.context.staging_run_id,
            run_directory=run_directory,
            resolver=resolver,
            cml=cml,
            terraform=terraform,
            credentials=credentials,
            readiness=ProtectedReadinessProbe(),
            host_trust=ProtectedSSHHostTrust(
                self.config.tools.ssh_keyscan, self.config.tools.ssh_keygen
            ),
            validator=ProtectedNCDPReadOnlyValidator(
                self.config.bundle_root,
                self.config.tools.ssh_keygen,
                self.config.tools.ansible_collections_root,
            ),
        )
        return operations, run_directory

    def recover(self, build_id: UUID) -> None:
        """Recover only one exact retained build with no create/start capability."""
        if self.context is not None:
            raise ProtectedStagingError("recovery requires trusted operator context")
        run_directory = self.config.state_root / "ephemeral" / f"bk-{build_id}"
        try:
            username = self._cml_username.decode("utf-8").strip()
            password = self._cml_password.decode("utf-8").strip()
            ca_pem = self._cml_ca.decode("ascii")
        except UnicodeDecodeError:
            raise ProtectedStagingError(
                "protected credential encoding rejected"
            ) from None
        cml = ProtectedCMLClient(
            self.manifest.cml,
            ProtectedCMLCredentials(username, password),
            ssl_context=build_cml_ssl_context(self._cml_ca, self.manifest),
        )
        cml.authenticate()
        variables = {
            "TF_VAR_staging_run_id": f"bk-{build_id}",
            "TF_VAR_lifecycle_state": "STARTED",
            "TF_VAR_cisco_bootstrap_hostname": "stg-core-02",
            "TF_VAR_cisco_bootstrap_management_cidr": "192.168.4.30/24",
            "TF_VAR_cisco_bootstrap_username": "ncdp-recovery",
            "TF_VAR_cisco_bootstrap_password": "recovery-placeholder",
            "TF_VAR_junos_bootstrap_hostname": "stg-edge-junos-01",
            "TF_VAR_junos_bootstrap_management_cidr": "192.168.4.31/24",
            "TF_VAR_junos_bootstrap_username": "ncdp-recovery",
            "TF_VAR_junos_bootstrap_password_hash": ("$6$ncdpedgejunos01$" + "A" * 86),
        }
        environment = build_protected_terraform_environment(
            terraform_data_dir=run_directory / "terraform-data",
            cml_address=self.manifest.cml.controller_url,
            cml_token=cml.bearer,
            cml_ca_pem=ca_pem,
            variables=variables,
            trusted_path=str(self.config.tools.terraform.parent),
        )
        terraform = ProtectedTerraformExecutor(
            self.config.bundle_root,
            run_directory,
            SubprocessTerraformRunner(self.config.tools.terraform),
            environment,
        )
        terraform.initialize()
        recover_protected_run(
            build_id,
            self.config.state_root,
            self.checkout,
            self.manifest,
            ProtectedRecoveryOperations(cml, terraform),
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="operation", required=True)
    subcommands.add_parser("run")
    recover = subcommands.add_parser("recover")
    recover.add_argument("--build-id", required=True, type=UUID)
    arguments = parser.parse_args()
    try:
        controller = ProtectedStagingController.load(
            checkout=Path.cwd(), recovery=arguments.operation == "recover"
        )
        if arguments.operation == "recover":
            controller.recover(arguments.build_id)
            print('{"recovery_result":"passed"}')
            return 0
        operations, run_directory = controller.compose()
        evidence = controller.run(operations, run_directory)
        print(evidence.safe_json())
        return 0 if evidence.overall_result == "passed" else 1
    except Exception:
        print("protected staging rejected")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
