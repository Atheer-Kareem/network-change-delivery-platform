#!/usr/bin/env python3
"""Run one explicitly authorized profiled exact-four CML staging lifecycle.

The entry point is intentionally not wired into Buildkite in Phase 1. It does
nothing unless an operator supplies ``--execute`` for a private run directory.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

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
    ProfiledStagingDeviceEvidence,
    ProfiledStagingError,
    ProfiledStagingLifecycle,
    terraform_profiled_device_variables,
    topology_digest,
    validate_management_only_bootstrap,
    validate_private_run_directory,
    validate_profiled_staging_physical_topology,
    validate_profiled_staging_population,
    validate_read_only_collection,
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
        self._data_directory = run_directory / "terraform-data"
        self._inventory = NetBoxProfileInventoryProvider()
        self._secrets = OpenBaoSecretProvider()
        self._devices = ()
        self._credentials: dict[str, object] = {}
        self._variables: dict[str, object] | None = None

    @property
    def managed_resources_exist(self) -> bool:
        return self._state_path.exists() and bool(self._state_addresses())

    def _environment(self, devices: dict[str, object] | None = None) -> dict[str, str]:
        values = dict(os.environ)
        values["TF_DATA_DIR"] = str(self._data_directory)
        if devices is not None:
            values["TF_VAR_devices"] = json.dumps(devices, separators=(",", ":"))
        values["TF_VAR_staging_run_id"] = self._run_id
        values["TF_VAR_lifecycle_state"] = "DEFINED_ON_CORE"
        return values

    def _terraform(
        self,
        arguments: list[str],
        *,
        phase: str,
        devices: dict[str, object] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["terraform", f"-chdir={TERRAFORM_ROOT}", *arguments],
            cwd=ROOT,
            env=self._environment(devices),
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ProfiledStagingError(f"profiled staging Terraform {phase} failed")
        return result

    def _state_addresses(self) -> set[str]:
        if not self._state_path.exists():
            return set()
        result = self._terraform(
            ["state", "list"], phase="state inspection", devices=self._variables
        )
        return {line for line in result.stdout.splitlines() if line}

    def _planned_actions(
        self, plan: Path, *, devices: dict[str, object]
    ) -> dict[str, str]:
        result = self._terraform(
            ["show", "-json", str(plan)], phase="plan inspection", devices=devices
        )
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
            if (
                not isinstance(address, str)
                or not isinstance(verbs, list)
                or len(verbs) != 1
                or verbs[0] not in {"create", "update", "delete"}
            ):
                raise ProfiledStagingError("profiled staging Terraform plan rejected")
            actions[address] = verbs[0]
        return actions

    def _apply_exact_create(self, devices: dict[str, object]) -> None:
        plan = self._run_directory / "create.tfplan"
        self._terraform(
            [
                "init",
                "-backend-config=" + f"path={self._state_path}",
                "-input=false",
                "-lockfile=readonly",
            ],
            phase="init",
            devices=devices,
        )
        self._terraform(
            ["plan", "-out", str(plan), "-input=false"],
            phase="create plan",
            devices=devices,
        )
        actions = self._planned_actions(plan, devices=devices)
        if set(actions) != PROFILED_STAGING_TERRAFORM_ADDRESSES or set(
            actions.values()
        ) != {"create"}:
            raise ProfiledStagingError("profiled staging create graph rejected")
        self._terraform(
            ["apply", "-input=false", str(plan)], phase="create", devices=devices
        )

    def _outputs(self, devices: dict[str, object]) -> dict[str, object]:
        result = self._terraform(
            ["output", "-json"], phase="output inspection", devices=devices
        )
        try:
            output = json.loads(result.stdout)
            lab_id = output["lab_id"]["value"]
            lab_title = output["lab_title"]["value"]
            node_ids = output["node_ids"]["value"]
        except (KeyError, TypeError, ValueError):
            raise ProfiledStagingError(
                "profiled staging Terraform outputs rejected"
            ) from None
        if (
            not isinstance(lab_id, str)
            or not isinstance(lab_title, str)
            or lab_title != f"NCDP Staging {self._run_id}"
            or not isinstance(node_ids, dict)
        ):
            raise ProfiledStagingError("profiled staging Terraform outputs rejected")
        return {"lab_id": lab_id, "lab_title": lab_title, "node_ids": node_ids}

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
        for template in (TERRAFORM_ROOT / "bootstrap").glob("*.tftpl"):
            validate_management_only_bootstrap(template.read_text(encoding="utf-8"))
        self._apply_exact_create(variables)
        outputs = self._outputs(variables)
        self._terraform(
            [
                "apply",
                "-input=false",
                "-auto-approve",
                "-var",
                "lifecycle_state=STARTED",
            ],
            phase="start",
            devices=variables,
        )
        self._wait_readiness()
        now = datetime.now(UTC)
        node_ids = outputs["node_ids"]
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
                    identity=f"staging-readiness:{self._run_id}:{device.logical_name}",
                    digest=topology_digest(),
                ),
                trust_evidence=EvidenceReference(
                    identity=f"staging-trust:{self._run_id}", digest=topology_digest()
                ),
            )
            for device in self._devices
        )
        context = StagingRealizationContext(
            staging_run_id=self._run_id,
            cml_lab_id=outputs["lab_id"],
            cml_lab_title=outputs["lab_title"],
            lifecycle_state=RealizationLifecycleState.READY,
            admitted_at=now,
            expires_at=now + timedelta(hours=1),
            topology_evidence=EvidenceReference(
                identity=f"staging-topology:{self._run_id}", digest=topology_digest()
            ),
            devices=provisional,
        )
        generation = establish_profiled_staging_trust(
            context, self._devices, self._run_directory / "trust"
        )
        return context.model_copy(
            update={
                "devices": tuple(
                    item.model_copy(
                        update={"trust_evidence": generation.generation_evidence}
                    )
                    for item in context.devices
                )
            }
        )

    def _wait_readiness(self) -> None:
        deadline = time.monotonic() + _READINESS_TIMEOUT_SECONDS
        remaining = set(self._devices)
        while remaining and time.monotonic() < deadline:
            for device in tuple(remaining):
                endpoint = device.management_endpoints.staging.binding.l3_endpoint
                try:
                    with socket.create_connection(
                        (str(endpoint.address.ip), endpoint.port), timeout=3
                    ):
                        remaining.remove(device)
                except OSError:
                    continue
            if remaining:
                time.sleep(5)
        if remaining:
            raise ProfiledStagingError("profiled staging readiness timed out")

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
        )

    def destroy(self, _context: StagingRealizationContext) -> None:
        self._terraform(
            ["destroy", "-input=false", "-auto-approve"],
            phase="destroy",
            devices=self._variables,
        )

    def verify_absent(self, context: StagingRealizationContext) -> None:
        if self._state_addresses():
            raise ProfiledStagingError("profiled staging Terraform state remains")
        address = os.environ.get("CML2_ADDRESS")
        token = os.environ.get("CML2_TOKEN")
        certificate = os.environ.get("CML2_CACERT")
        if not address or not token or not certificate:
            raise ProfiledStagingError("profiled staging CML absence authority missing")
        client = httpx.Client(
            base_url=address.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            verify=ssl.create_default_context(cadata=certificate),
            timeout=10,
            trust_env=False,
        )
        try:
            response = client.get(f"/api/v0/labs/{context.cml_lab_id}")
        except httpx.HTTPError:
            raise ProfiledStagingError(
                "profiled staging absence cannot be proven"
            ) from None
        finally:
            client.close()
        if response.status_code != 404:
            raise ProfiledStagingError("profiled staging absence cannot be proven")

    def retire_state(self) -> None:
        for path in (self._state_path, self._run_directory / "create.tfplan"):
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
