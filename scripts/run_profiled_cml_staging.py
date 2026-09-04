#!/usr/bin/env python3
"""Run one explicitly authorized profiled exact-four CML staging lifecycle.

The entry point is intentionally not wired into Buildkite in Phase 1. It does
nothing unless an operator supplies ``--execute`` for a private run directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from network_change_delivery.architecture_contracts import get_automation_profile
from network_change_delivery.profile_inventory import NetBoxProfileInventoryProvider
from network_change_delivery.profile_read_only_adapter import ProfileReadOnlyAdapter
from network_change_delivery.profiled_live_cml import ios_scrypt_password_hash
from network_change_delivery.profiled_realization import (
    EvidenceReference,
    RealizationLifecycleState,
    StagingRealizationContext,
    StagingRealizedDevice,
)
from network_change_delivery.profiled_staging import (
    PROFILED_STAGING_TERRAFORM_ADDRESSES,
    ProfiledStagingAmbiguousError,
    ProfiledStagingDeviceEvidence,
    ProfiledStagingError,
    ProfiledStagingLifecycle,
    load_recovery_inputs,
    terraform_managed_state_addresses,
    terraform_profiled_device_variables,
    validate_destroy_only_plan,
    validate_management_only_bootstrap,
    validate_private_run_directory,
    validate_profiled_staging_physical_topology,
    validate_profiled_staging_population,
    validate_read_only_collection,
    validate_retained_state_file,
    validate_start_only_plan,
    write_recovery_inputs,
)
from network_change_delivery.profiled_staging_cml import (
    ProfiledStagingCmlReader,
    admit_created_realization,
    admit_no_staging_collision,
)
from network_change_delivery.profiled_staging_trust import (
    KNOWN_HOSTS_NAME,
    establish_profiled_staging_trust,
)
from network_change_delivery.secrets import OpenBaoSecretProvider

ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_ROOT = ROOT / "infrastructure" / "cml" / "profiled-staging"
_READINESS_TIMEOUT_SECONDS = 900


class LocalTerraformOperations:
    """Explicit local Terraform/CML lifecycle with no device write operation."""

    def __init__(self, run_id: str, run_directory: Path) -> None:
        self._run_id = run_id
        self._run_directory = run_directory
        self._state_path = run_directory / "terraform.tfstate"
        self._state_backup_path = run_directory / "terraform.tfstate.backup"
        self._data_directory = run_directory / "terraform-data"
        self._recovery_inputs = run_directory / "recovery-inputs.tfvars.json"
        self._inventory = NetBoxProfileInventoryProvider()
        self._secrets = OpenBaoSecretProvider()
        self._devices = ()
        self._credentials: dict[str, object] = {}
        self._variables: dict[str, object] | None = None
        self._owned_lab_id: str | None = None
        self._readiness: dict[str, tuple[float, EvidenceReference]] = {}
        self.topology_digest: str | None = None
        self.trust_generation: EvidenceReference | None = None
        self.device_evidence: tuple[ProfiledStagingDeviceEvidence, ...] = ()
        self.create_stage = "not_attempted"
        self.start_stage = "not_attempted"

    @property
    def source_commit(self) -> str:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    @property
    def owned_lab_id(self) -> str | None:
        return self._owned_lab_id

    @property
    def managed_resources_exist(self) -> bool:
        if not self._state_path.exists():
            return False
        try:
            return bool(self._state_addresses())
        except ProfiledStagingError:
            raise ProfiledStagingAmbiguousError(
                "profiled staging Terraform ownership cannot be proven"
            ) from None

    def _environment(self) -> dict[str, str]:
        values = dict(os.environ)
        values["TF_DATA_DIR"] = str(self._data_directory)
        return values

    def _var_file_arguments(self) -> list[str]:
        load_recovery_inputs(self._recovery_inputs, self._run_id)
        return [f"-var-file={self._recovery_inputs}"]

    @staticmethod
    def _secure_file(path: Path) -> None:
        if path.is_symlink() or not path.is_file():
            raise ProfiledStagingError("profiled staging private artifact rejected")
        path.chmod(0o600, follow_symlinks=False)

    def _terraform(
        self,
        arguments: list[str],
        *,
        phase: str,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["terraform", f"-chdir={TERRAFORM_ROOT}", *arguments],
            cwd=ROOT,
            env=self._environment(),
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            if phase in {"create", "START apply", "destroy apply"}:
                if (
                    self._state_path.is_symlink()
                    or self._state_backup_path.is_symlink()
                ):
                    raise ProfiledStagingAmbiguousError(
                        f"profiled staging Terraform {phase} ownership is ambiguous"
                    )
                if self._state_path.exists() and not self._state_path.is_symlink():
                    self._state_path.chmod(0o600, follow_symlinks=False)
                if (
                    self._state_backup_path.exists()
                    and not self._state_backup_path.is_symlink()
                ):
                    self._state_backup_path.chmod(0o600, follow_symlinks=False)
                state = subprocess.run(
                    [
                        "terraform",
                        f"-chdir={TERRAFORM_ROOT}",
                        "show",
                        "-json",
                    ],
                    cwd=ROOT,
                    env=self._environment(),
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if state.returncode != 0:
                    raise ProfiledStagingAmbiguousError(
                        f"profiled staging Terraform {phase} outcome is ambiguous"
                    )
                try:
                    addresses = terraform_managed_state_addresses(
                        json.loads(state.stdout)
                    )
                except (ValueError, ProfiledStagingError):
                    raise ProfiledStagingAmbiguousError(
                        f"profiled staging Terraform {phase} ownership is ambiguous"
                    ) from None
                if not addresses.issubset(PROFILED_STAGING_TERRAFORM_ADDRESSES):
                    raise ProfiledStagingAmbiguousError(
                        f"profiled staging Terraform {phase} ownership is ambiguous"
                    )
                if phase == "destroy apply" or not addresses:
                    raise ProfiledStagingAmbiguousError(
                        f"profiled staging Terraform {phase} outcome is ambiguous"
                    )
            raise ProfiledStagingError(f"profiled staging Terraform {phase} failed")
        return result

    def _state_addresses(self) -> set[str]:
        if not self._state_path.exists():
            return set()
        validate_retained_state_file(self._state_path)
        result = self._terraform(["show", "-json"], phase="state inspection")
        try:
            payload = json.loads(result.stdout)
        except ValueError:
            raise ProfiledStagingError(
                "profiled staging Terraform state rejected"
            ) from None
        return terraform_managed_state_addresses(payload)

    def _planned_actions(self, plan: Path) -> dict[str, str]:
        result = self._terraform(["show", "-json", str(plan)], phase="plan inspection")
        try:
            payload = json.loads(result.stdout)
            changes = payload["resource_changes"]
        except (KeyError, TypeError, ValueError):
            raise ProfiledStagingError(
                "profiled staging Terraform plan rejected"
            ) from None
        actions: dict[str, str] = {}
        if not isinstance(changes, list):
            raise ProfiledStagingError("profiled staging Terraform plan rejected")
        for change in changes:
            if not isinstance(change, dict):
                raise ProfiledStagingError("profiled staging Terraform plan rejected")
            address = change.get("address")
            change_data = change.get("change")
            verbs = (
                change_data.get("actions") if isinstance(change_data, dict) else None
            )
            if change.get("mode") == "data" and verbs in (["read"], ["no-op"]):
                continue
            if isinstance(address, str) and verbs == ["no-op"]:
                continue
            if (
                not isinstance(address, str)
                or not isinstance(verbs, list)
                or len(verbs) != 1
                or verbs[0] not in {"create", "update", "delete"}
                or address in actions
            ):
                raise ProfiledStagingError("profiled staging Terraform plan rejected")
            actions[address] = verbs[0]
        return actions

    def _apply_exact_create(self) -> None:
        self.create_stage = "attempted"
        plan = self._run_directory / "create.tfplan"
        self._terraform(
            [
                "init",
                "-backend-config=" + f"path={self._state_path}",
                "-reconfigure",
                "-input=false",
                "-lockfile=readonly",
            ],
            phase="init",
        )
        self._terraform(
            ["plan", *self._var_file_arguments(), "-out", str(plan), "-input=false"],
            phase="create plan",
        )
        self._secure_file(plan)
        actions = self._planned_actions(plan)
        if set(actions) != PROFILED_STAGING_TERRAFORM_ADDRESSES or set(
            actions.values()
        ) != {"create"}:
            raise ProfiledStagingError("profiled staging create graph rejected")
        self._terraform(["apply", "-input=false", str(plan)], phase="create")
        if self._state_path.exists():
            self._secure_file(self._state_path)
        if self._state_backup_path.exists():
            self._secure_file(self._state_backup_path)
        self.create_stage = "succeeded"

    def _apply_start(self) -> None:
        self.start_stage = "attempted"
        plan = self._run_directory / "start.tfplan"
        self._terraform(
            [
                "plan",
                *self._var_file_arguments(),
                "-var",
                "lifecycle_state=STARTED",
                "-out",
                str(plan),
                "-input=false",
            ],
            phase="START plan",
        )
        self._secure_file(plan)
        validate_start_only_plan(self._planned_actions(plan))
        self._terraform(["apply", "-input=false", str(plan)], phase="START apply")
        self.start_stage = "succeeded"

    def _state_lab_binding(self) -> tuple[str, str]:
        result = self._terraform(["show", "-json"], phase="state inspection")
        try:
            payload = json.loads(result.stdout)
            resources = payload["values"]["root_module"]["resources"]
            lab = next(
                item
                for item in resources
                if item.get("address") == "cml2_lab.profiled_staging"
            )
            lab_id = lab["values"]["id"]
            title = lab["values"]["title"]
        except (KeyError, StopIteration, TypeError, ValueError):
            raise ProfiledStagingAmbiguousError(
                "profiled staging retained lab ownership is ambiguous"
            ) from None
        if not isinstance(lab_id, str) or title != f"NCDP Staging {self._run_id}":
            raise ProfiledStagingAmbiguousError(
                "profiled staging retained lab ownership is ambiguous"
            )
        self._owned_lab_id = lab_id
        return lab_id, title

    def _outputs(self) -> dict[str, object]:
        result = self._terraform(["output", "-json"], phase="output inspection")
        try:
            output = json.loads(result.stdout)
            lab_id = output["lab_id"]["value"]
            lab_title = output["lab_title"]["value"]
            node_ids = output["node_ids"]["value"]
            link_ids = output["link_ids"]["value"]
        except (KeyError, TypeError, ValueError):
            raise ProfiledStagingError(
                "profiled staging Terraform outputs rejected"
            ) from None
        if (
            not isinstance(lab_id, str)
            or not isinstance(lab_title, str)
            or lab_title != f"NCDP Staging {self._run_id}"
            or not isinstance(node_ids, dict)
            or not isinstance(link_ids, dict)
        ):
            raise ProfiledStagingError("profiled staging Terraform outputs rejected")
        self._owned_lab_id = lab_id
        return {
            "lab_id": lab_id,
            "lab_title": lab_title,
            "node_ids": node_ids,
            "link_ids": link_ids,
        }

    @staticmethod
    def _junos_verifier(password: str) -> str:
        result = subprocess.run(
            ["openssl", "passwd", "-6", "-stdin"],
            input=password,
            check=False,
            capture_output=True,
            text=True,
        )
        verifier = result.stdout.strip()
        if result.returncode != 0 or not verifier.startswith("$6$"):
            raise ProfiledStagingError("profiled staging Junos verifier rejected")
        return verifier

    def admit(self) -> None:
        self._devices = validate_profiled_staging_population(self._inventory)
        validate_profiled_staging_physical_topology(self._inventory, self._devices)
        reader = ProfiledStagingCmlReader.from_environment()
        try:
            admit_no_staging_collision(reader, self._devices)
        finally:
            reader.close()
        for device in self._devices:
            reference = self._secrets.reference(device)
            expected = (
                "openbao:kv-v2:ncdp/devices/"
                + device.device_identity.rsplit(":", 1)[1]
                + "/ssh"
            )
            if reference.reference != expected:
                raise ProfiledStagingError(
                    "profiled staging credential reference rejected"
                )
            self._credentials[str(device.logical_name)] = self._secrets.load(device)

    def create(self) -> StagingRealizationContext:
        credentials = self._credentials
        if len(credentials) != 4:
            raise ProfiledStagingError(
                "profiled staging credential population rejected"
            )
        password_verifiers = {}
        for device in self._devices:
            credential = credentials[str(device.logical_name)]
            if device.automation_profile_id.value == "vjunos_router":
                password_verifiers[str(device.logical_name)] = self._junos_verifier(
                    credential.password
                )
            else:
                password_verifiers[str(device.logical_name)] = ios_scrypt_password_hash(
                    credential.password,
                    device.device_identity.rsplit(":", 1)[1].zfill(14),
                )
        variables = terraform_profiled_device_variables(
            self._devices, credentials, password_verifiers
        )
        self._variables = variables
        write_recovery_inputs(
            self._recovery_inputs,
            {
                "staging_run_id": self._run_id,
                "lifecycle_state": "DEFINED_ON_CORE",
                "devices": variables,
            },
        )
        for template in (TERRAFORM_ROOT / "bootstrap").glob("*.tftpl"):
            validate_management_only_bootstrap(template.read_text(encoding="utf-8"))
        self._apply_exact_create()
        outputs = self._outputs()
        reader = ProfiledStagingCmlReader.from_environment()
        try:
            observed = admit_created_realization(
                reader, self._run_id, outputs, self._devices
            )
            self.topology_digest = observed.topology_evidence.digest
        finally:
            reader.close()
        self._apply_start()
        self._readiness = self._wait_readiness(observed.node_ids, observed.lab_id)
        now = datetime.now(UTC)
        node_ids = observed.node_ids
        if not isinstance(node_ids, dict):
            raise ProfiledStagingError("profiled staging node outputs rejected")
        provisional = tuple(
            StagingRealizedDevice(
                device_identity=device.device_identity,
                logical_name=device.logical_name,
                operational_role=device.operational_role,
                automation_profile_id=device.automation_profile_id,
                cml_realization_profile_id=device.cml_realization_profile_id,
                cml_node_id=node_ids[str(device.logical_name).replace("-", "_")],
                staging_endpoint=device.management_endpoints.staging,
                readiness_evidence=EvidenceReference(
                    identity=self._readiness[str(device.logical_name)][1].identity,
                    digest=self._readiness[str(device.logical_name)][1].digest,
                ),
                trust_evidence=None,
            )
            for device in self._devices
        )
        context = StagingRealizationContext(
            staging_run_id=self._run_id,
            cml_lab_id=observed.lab_id,
            cml_lab_title=observed.lab_title,
            lifecycle_state=RealizationLifecycleState.PREPARING,
            admitted_at=now,
            expires_at=now + timedelta(hours=1),
            topology_evidence=observed.topology_evidence,
            devices=provisional,
        )
        generation = establish_profiled_staging_trust(
            context,
            self._devices,
            self._run_directory / "trust",
            observed.cml_anchors,
        )
        self.trust_generation = generation.generation_evidence
        return StagingRealizationContext.model_validate(
            context.model_dump(mode="python")
            | {
                "lifecycle_state": RealizationLifecycleState.READY,
                "devices": tuple(
                    item.model_dump(mode="python")
                    | {"trust_evidence": generation.generation_evidence}
                    for item in context.devices
                ),
            }
        )

    def _wait_readiness(
        self, node_ids: dict[str, str], lab_id: str
    ) -> dict[str, tuple[float, EvidenceReference]]:
        deadline = time.monotonic() + _READINESS_TIMEOUT_SECONDS
        started = {
            str(device.logical_name): time.monotonic() for device in self._devices
        }
        observed: dict[str, tuple[float, EvidenceReference]] = {}
        remaining = set(self._devices)
        while remaining and time.monotonic() < deadline:
            for device in tuple(remaining):
                endpoint = device.management_endpoints.staging.binding.l3_endpoint
                try:
                    with socket.create_connection(
                        (str(endpoint.address.ip), endpoint.port), timeout=3
                    ):
                        remaining.remove(device)
                        elapsed = time.monotonic() - started[str(device.logical_name)]
                        facts = {
                            "run_id": self._run_id,
                            "lab_id": lab_id,
                            "node_id": node_ids[
                                str(device.logical_name).replace("-", "_")
                            ],
                            "device_identity": device.device_identity,
                            "address": str(endpoint.address.ip),
                            "service": get_automation_profile(
                                device.automation_profile_id
                            )
                            .readiness_services[0]
                            .service,
                            "port": endpoint.port,
                            "ready": True,
                            "elapsed_seconds": elapsed,
                        }
                        digest = (
                            "sha256:"
                            + hashlib.sha256(
                                json.dumps(
                                    facts,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                    default=str,
                                ).encode()
                            ).hexdigest()
                        )
                        observed[str(device.logical_name)] = (
                            elapsed,
                            EvidenceReference(
                                identity=f"staging-readiness:{self._run_id}:{device.logical_name}",
                                digest=digest,
                            ),
                        )
                except OSError:
                    continue
            if remaining:
                time.sleep(5)
        if remaining:
            raise ProfiledStagingError("profiled staging readiness timed out")
        return observed

    def validate(
        self, context: StagingRealizationContext
    ) -> tuple[ProfiledStagingDeviceEvidence, ...]:
        return validate_read_only_collection(
            context,
            self._devices,
            self._credentials,
            ProfileReadOnlyAdapter(
                known_hosts=self._run_directory / "trust" / KNOWN_HOSTS_NAME
            ),
            self._readiness,
            lambda evidence: setattr(self, "device_evidence", evidence),
        )

    def destroy_owned(self, *, require_complete: bool) -> None:
        state = self._state_addresses()
        if self._owned_lab_id is None:
            self._state_lab_binding()
        plan = self._run_directory / "destroy.tfplan"
        self._terraform(
            [
                "plan",
                *self._var_file_arguments(),
                "-destroy",
                "-out",
                str(plan),
                "-input=false",
            ],
            phase="destroy plan",
        )
        self._secure_file(plan)
        validate_destroy_only_plan(
            state, self._planned_actions(plan), require_complete=require_complete
        )
        try:
            self._terraform(["apply", "-input=false", str(plan)], phase="destroy apply")
        except ProfiledStagingAmbiguousError:
            try:
                state_after = self._state_addresses()
            except ProfiledStagingError:
                raise ProfiledStagingAmbiguousError(
                    "profiled staging Terraform destroy outcome is ambiguous"
                ) from None
            if state_after or not self._lab_is_absent():
                raise

    def _lab_is_absent(self) -> bool:
        if self._owned_lab_id is None:
            return False
        reader = ProfiledStagingCmlReader.from_environment()
        try:
            return reader.lab(self._owned_lab_id, allow_missing=True) is None
        finally:
            reader.close()

    def verify_absent(self) -> None:
        if self._state_addresses():
            raise ProfiledStagingError("profiled staging Terraform state remains")
        if self._owned_lab_id is None:
            raise ProfiledStagingError("profiled staging absence identity unavailable")
        if not self._lab_is_absent():
            raise ProfiledStagingError("profiled staging absence cannot be proven")

    def retire_state(self) -> None:
        for path in (
            self._state_path,
            self._state_backup_path,
            self._recovery_inputs,
            self._run_directory / "create.tfplan",
            self._run_directory / "start.tfplan",
            self._run_directory / "destroy.tfplan",
        ):
            if path.exists() and not path.is_symlink():
                path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-directory", type=Path, required=True)
    parser.add_argument("--evidence-json", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    arguments = parser.parse_args()
    descriptor: int | None = None
    try:
        run = validate_private_run_directory(arguments.run_directory, ROOT)
        if run.name != arguments.run_id:
            raise ProfiledStagingError("profiled staging run identity rejected")
        if not arguments.execute:
            raise ProfiledStagingError("profiled staging requires explicit --execute")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(arguments.evidence_json, flags, 0o600)
        evidence = ProfiledStagingLifecycle(
            arguments.run_id,
            "local",
            LocalTerraformOperations(arguments.run_id, run),
        ).run()
    except (OSError, ValueError, ProfiledStagingError) as error:
        if descriptor is not None:
            os.close(descriptor)
            descriptor = None
            arguments.evidence_json.unlink(missing_ok=True)
        print(f"profiled staging admission failed: {error}")
        return 2
    finally:
        if descriptor is not None:
            payload = (evidence.model_dump_json(indent=2) + "\n").encode()
            os.write(descriptor, payload)
            os.fsync(descriptor)
            os.close(descriptor)
    print(
        "profiled staging outcome="
        f"{evidence.final_outcome.value} create={evidence.create_outcome} "
        f"destroy={evidence.destroy_outcome}"
    )
    return 0 if evidence.final_outcome.value == "SUCCEEDED" else 2


if __name__ == "__main__":  # pragma: no cover - explicit operator entry point
    raise SystemExit(main())
