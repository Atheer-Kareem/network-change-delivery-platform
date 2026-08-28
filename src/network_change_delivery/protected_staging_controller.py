"""Entry point for the future externally installed protected staging controller."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from network_change_delivery.buildkite_staging import (
    BuildkiteStagingContext,
    staging_context_from_environment,
)
from network_change_delivery.protected_staging import (
    ExecutionToolAuthority,
    ProtectedCMLClient,
    ProtectedCMLCredentials,
    ProtectedStagingError,
    ProtectedStagingInventoryResolver,
    ProtectedStagingManifest,
    ProtectedTerraformExecutor,
    ServiceIdentityAuthority,
    SubprocessTerraformRunner,
    request_staging_oidc_jwt,
    validate_protected_bundle,
    validate_runtime_artifacts,
    validate_runtime_inventory,
)
from network_change_delivery.protected_staging_runtime import (
    LifecycleIdentity,
    ProcessIdentity,
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
    directory_inventory_sha256,
    load_protected_staging_credentials,
    read_root_owned_service_file,
    recover_protected_run,
    run_protected_lifecycle,
    terraform_version_runner,
    validate_root_owned_executable,
    validate_root_owned_service_directory,
    validate_service_identity,
    validate_service_owned_private_path,
    verify_ca_digest,
)

PROTECTED_CONTROLLER_CONFIG = Path(
    "/private/var/db/ncdp-staging/authority/config/protected-controller.json"
)


class ProtectedControllerConfig(BaseModel):
    """Agent-owned locations; none may be supplied through checkout arguments."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[4] = 4
    install_root: Path
    source_bundle_root: Path
    runtime_root: Path
    manifest_path: Path
    source_inventory_path: Path
    runtime_inventory_path: Path
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
        process_identity: ProcessIdentity | None = None,
    ) -> ProtectedStagingController:
        if config_path != PROTECTED_CONTROLLER_CONFIG:
            raise ProtectedStagingError("protected controller config path rejected")
        observed = process_identity
        if observed is None:
            from network_change_delivery.protected_staging_runtime import (
                current_process_identity,
            )

            observed = current_process_identity()
        try:
            bootstrap_identity = ServiceIdentityAuthority(
                service_uid=observed.effective_uid,
                service_gid=observed.effective_gid,
                supplementary_gids=observed.supplementary_gids,
            )
            config = ProtectedControllerConfig.model_validate_json(
                read_root_owned_service_file(
                    config_path, checkout, bootstrap_identity
                ).decode()
            )
            manifest = ProtectedStagingManifest.model_validate_json(
                read_root_owned_service_file(
                    config.manifest_path, checkout, bootstrap_identity
                ).decode()
            )
        except (OSError, ValueError):
            raise ProtectedStagingError(
                "protected controller authority invalid"
            ) from None
        validate_service_identity(manifest.service_identity, observed)
        if manifest.service_identity != bootstrap_identity:
            raise ProtectedStagingError("protected service identity mismatch")
        for immutable_directory in (
            config.install_root,
            config.source_bundle_root,
            config.runtime_root,
            config.install_root / "artifacts",
        ):
            validate_root_owned_service_directory(
                immutable_directory, checkout, manifest.service_identity
            )
        validate_protected_bundle(
            config.source_bundle_root,
            checkout,
            manifest,
            service_identity=manifest.service_identity,
        )
        install_root = config.install_root.resolve(strict=True)
        if (
            config.source_bundle_root.resolve(strict=True).parent != install_root
            or config.runtime_root.resolve(strict=True).parent != install_root
            or config.manifest_path.resolve(strict=True)
            != install_root / "authority-manifest.json"
            or config.source_inventory_path.resolve(strict=True)
            != install_root / "source-files.json"
            or config.runtime_inventory_path.resolve(strict=True)
            != install_root / "runtime-files.json"
        ):
            raise ProtectedStagingError("protected installation layout mismatch")
        source_inventory = read_root_owned_service_file(
            config.source_inventory_path, checkout, manifest.service_identity
        )
        if (
            hashlib.sha256(source_inventory).hexdigest()
            != manifest.source_inventory_sha256
        ):
            raise ProtectedStagingError("protected source inventory digest mismatch")
        try:
            if json.loads(source_inventory) != manifest.file_digests:
                raise ProtectedStagingError("protected source inventory mismatch")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProtectedStagingError("protected source inventory invalid") from None
        validate_runtime_inventory(
            config.runtime_root,
            checkout,
            manifest,
            config.runtime_inventory_path,
            service_identity=manifest.service_identity,
        )
        validate_root_owned_executable(
            Path(manifest.python_interpreter_path),
            checkout,
            manifest.service_identity,
            ExecutionToolAuthority(
                path=manifest.python_interpreter_path,
                sha256=manifest.python_interpreter_sha256,
                version=manifest.python_version,
            ),
        )
        validate_runtime_artifacts(
            install_root, manifest, service_identity=manifest.service_identity
        )
        validate_service_owned_private_path(
            config.state_root, checkout, manifest.service_identity
        )
        netbox_token = read_root_owned_service_file(
            config.netbox_token_file, checkout, manifest.service_identity
        )
        cml_username = read_root_owned_service_file(
            config.cml_username_file, checkout, manifest.service_identity
        )
        cml_password = read_root_owned_service_file(
            config.cml_password_file, checkout, manifest.service_identity
        )
        cml_ca = read_root_owned_service_file(
            config.cml_ca_file, checkout, manifest.service_identity
        )
        verify_ca_digest(cml_ca, manifest)
        validate_root_owned_executable(
            config.tools.buildkite_agent,
            checkout,
            manifest.service_identity,
            manifest.buildkite_agent,
        )
        validate_root_owned_executable(
            config.tools.terraform,
            checkout,
            manifest.service_identity,
            manifest.terraform,
            observed_version=terraform_version_runner(config.tools.terraform, ()),
        )
        for path, authority in (
            (config.tools.openssl, manifest.openssl),
            (config.tools.ssh_keyscan, manifest.ssh_keyscan),
            (config.tools.ssh_keygen, manifest.ssh_keygen),
        ):
            validate_root_owned_executable(
                path, checkout, manifest.service_identity, authority
            )
        if (
            str(config.tools.ansible_collections_root)
            != manifest.ansible_collections_root
        ):
            raise ProtectedStagingError("protected Ansible authority mismatch")
        validate_root_owned_service_directory(
            config.tools.ansible_collections_root,
            checkout,
            manifest.service_identity,
        )
        if (
            directory_inventory_sha256(config.tools.ansible_collections_root)
            != manifest.ansible_inventory_sha256
        ):
            raise ProtectedStagingError("protected Ansible inventory mismatch")
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
            self.config.source_bundle_root,
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
                self.config.source_bundle_root,
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
            self.config.source_bundle_root,
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
