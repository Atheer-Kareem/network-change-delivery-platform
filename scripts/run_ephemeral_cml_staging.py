#!/usr/bin/env python3
"""Run one local ephemeral CML staging lifecycle with sanitized evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from network_change_delivery.ansible_adapter import (
    AnsibleRunnerCiscoAdapter,
    ProviderError,
)
from network_change_delivery.buildkite_identity import (
    BuildkiteOIDCJWT,
    read_buildkite_oidc_jwt,
)
from network_change_delivery.buildkite_staging import (
    BuildkiteStagingContext,
    BuildkiteStagingSecretProvider,
    staging_context_from_environment,
    validate_staging_state_root,
)
from network_change_delivery.ephemeral_staging import (
    StagingError,
    StagingEvidence,
    run_staging_lifecycle,
    validate_recovery_destroy_graph,
    validate_run_directory,
)
from network_change_delivery.inventory import NetBoxInventoryProvider
from network_change_delivery.junos_adapter import JunosPyEZAdapter
from network_change_delivery.models import (
    DesiredDescription,
    InterfaceDescriptionIntent,
    InventoryDevice,
)
from network_change_delivery.secrets import (
    CredentialReference,
    DeviceCredentials,
    OpenBaoSecretProvider,
)
from network_change_delivery.workflow import plan_change

ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_ROOT = ROOT / "infrastructure" / "cml" / "ephemeral"
SAFE_UI = ROOT / "scripts" / "terraform_cml_safe_ui.py"
EXPECTED_NODES = frozenset(
    {"system_bridge", "management_switch", "core_02", "edge_junos_01", "core_03"}
)
EXPECTED_LINKS = frozenset(
    {
        "system_bridge_management",
        "management_core_02",
        "management_edge_junos_01",
        "management_core_03",
        "core_02_edge_junos_01",
        "edge_junos_01_core_03",
    }
)
LEGACY_LAB = "09605569-0468-4fc4-8684-beb5a1342b9c"
SCRATCH_LAB = "a824a8b3-bcd1-488a-a791-d0783594ad9a"


class CachedSecrets:
    """Reuse credentials already resolved once from OpenBao."""

    def __init__(self, values: dict[str, DeviceCredentials]) -> None:
        self._values = values

    @staticmethod
    def reference(device: InventoryDevice) -> CredentialReference:
        return CredentialReference(
            "openbao",
            "openbao:kv-v2:ncdp/devices/"
            f"{device.inventory_object_id.rsplit(':', 1)[1]}/ssh",
        )

    def load(self, device: InventoryDevice) -> DeviceCredentials:
        return self._values[device.name]


class LocalOperations:
    def __init__(
        self,
        run_id: str,
        run_directory: Path,
        *,
        buildkite_context: BuildkiteStagingContext | None = None,
        buildkite_jwt: BuildkiteOIDCJWT | None = None,
    ) -> None:
        self.run_id = run_id
        self.run_directory = run_directory
        self.data_directory = run_directory / "terraform-data"
        self.state_path = run_directory / "terraform.tfstate"
        self.lab_title = f"NCDP Staging {run_id}"
        self._managed = False
        self._outputs: dict[str, Any] = {}
        self._devices: dict[str, InventoryDevice] = {}
        self._credentials: dict[str, DeviceCredentials] = {}
        self._inventory: NetBoxInventoryProvider | None = None
        self._buildkite_context = buildkite_context
        self._buildkite_jwt = buildkite_jwt
        if (buildkite_context is None) != (buildkite_jwt is None):
            raise StagingError("staging identity boundary is incomplete")
        self._client = self._cml_client(buildkite_context is not None)
        self._known_hosts = (
            run_directory / "known_hosts"
            if buildkite_context is not None
            else Path.home() / ".ssh" / "known_hosts"
        )
        self._terraform_env = os.environ.copy()
        authorization = self._client.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            raise StagingError("CML authentication failed")
        self._terraform_env["CML2_TOKEN"] = authorization.removeprefix("Bearer ")
        self._terraform_env["TF_DATA_DIR"] = str(self.data_directory)

    @property
    def managed_resources_exist(self) -> bool:
        if self._managed:
            return True
        return self.state_path.exists() and bool(self._state_list())

    @staticmethod
    def _cml_client(buildkite: bool) -> httpx.Client:
        address = os.environ.get("CML2_ADDRESS")
        certificate = os.environ.get("CML2_CACERT")
        token = os.environ.get("CML2_TOKEN")
        if not address or not certificate:
            raise StagingError("CML authentication environment is incomplete")
        if buildkite and token:
            raise StagingError("ambient CML token is prohibited in Buildkite staging")
        if not buildkite and not token:
            raise StagingError("CML authentication environment is incomplete")
        context = ssl.create_default_context(cadata=certificate)
        client = httpx.Client(
            base_url=address.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"} if token else {},
            verify=context,
            timeout=20,
            trust_env=False,
        )
        if buildkite:
            username = os.environ.get("NCDP_CML_STAGING_USERNAME")
            password = os.environ.get("NCDP_CML_STAGING_PASSWORD")
            if not username or not password:
                raise StagingError("dedicated CML staging identity is missing")
            probe = httpx.Response(401)
        else:
            try:
                probe = client.get("/api/v0/labs")
            except httpx.HTTPError:
                raise StagingError("CML authentication failed") from None
            username = os.environ.get("NCDP_CML_CONSOLE_USER")
            password = os.environ.get("NCDP_CML_CONSOLE_PASSWORD")
        if probe.status_code in {401, 403}:
            if not username or not password:
                raise StagingError("CML authentication failed")
            try:
                response = client.post(
                    "/api/v0/authenticate",
                    json={"username": username, "password": password},
                    headers={},
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError):
                raise StagingError("CML authentication failed") from None
            refreshed = payload if isinstance(payload, str) else payload.get("token")
            if not isinstance(refreshed, str) or not refreshed:
                raise StagingError("CML authentication failed")
            client.headers["Authorization"] = f"Bearer {refreshed}"
            probe = client.get("/api/v0/labs")
        if probe.status_code != 200:
            raise StagingError("CML authentication failed")
        return client

    def _resolve_authority(self) -> None:
        if self._buildkite_context is not None:
            token = os.environ.get("NCDP_STAGING_NETBOX_TOKEN")
            if not token:
                raise StagingError("dedicated NetBox staging credential is missing")
            if os.environ.get("NCDP_NETBOX_TOKEN"):
                raise StagingError(
                    "ambient NetBox token is prohibited in Buildkite staging"
                )
            inventory = NetBoxInventoryProvider(token=token)
            assert self._buildkite_jwt is not None
            bao = BuildkiteStagingSecretProvider(
                self._buildkite_jwt, self._buildkite_context
            )
        else:
            inventory = NetBoxInventoryProvider()
            bao = OpenBaoSecretProvider()
        self._inventory = inventory
        targets = {
            "core_02": ("core-02", "192.168.4.14", "cisco_iosxe"),
            "edge_junos_01": ("edge-junos-01", "192.168.4.20", "junos"),
        }
        for role, (name, host, platform) in targets.items():
            device = inventory.resolve(name)
            if (
                device.host != host
                or device.platform != platform
                or device.inventory_object_id
                != f"netbox:dcim.device:{1 if role == 'core_02' else 2}"
            ):
                raise StagingError(f"{name} authoritative identity mismatch")
            reference = bao.reference(device)
            expected = f"openbao:kv-v2:ncdp/devices/{1 if role == 'core_02' else 2}/ssh"
            if reference.reference != expected:
                raise StagingError(f"{name} credential reference mismatch")
            self._devices[role] = device
            self._credentials[name] = bao.load(device)
        if self._buildkite_context is not None:
            self._buildkite_jwt = None
        edge = self._credentials["edge-junos-01"]
        verifier = subprocess.run(
            ["openssl", "passwd", "-6", "-salt", "ncdpedgejunos01", "-stdin"],
            input=edge.password,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        if not re.fullmatch(r"\$6\$ncdpedgejunos01\$[A-Za-z0-9./]{86}", verifier):
            raise StagingError("Junos verifier derivation failed")
        self._terraform_env.update(
            {
                "TF_DATA_DIR": str(self.data_directory),
                "TF_VAR_staging_run_id": self.run_id,
                "TF_VAR_twin_lifecycle_state": "DEFINED_ON_CORE",
                "TF_VAR_core_02_bootstrap_hostname": "core-02",
                "TF_VAR_core_02_bootstrap_management_cidr": "192.168.4.14/24",
                "TF_VAR_core_02_bootstrap_username": self._credentials[
                    "core-02"
                ].username,
                "TF_VAR_core_02_bootstrap_password": self._credentials[
                    "core-02"
                ].password,
                "TF_VAR_edge_junos_01_bootstrap_hostname": "edge-junos-01",
                "TF_VAR_edge_junos_01_bootstrap_management_cidr": "192.168.4.20/24",
                "TF_VAR_edge_junos_01_bootstrap_username": edge.username,
                "TF_VAR_edge_junos_01_bootstrap_password_hash": verifier,
            }
        )

    def _api(self, path: str) -> Any:
        try:
            response = self._client.get(path)
        except httpx.HTTPError:
            raise StagingError("CML read-only inspection failed") from None
        if response.status_code != 200:
            raise StagingError("CML read-only inspection failed")
        try:
            return response.json()
        except ValueError:
            raise StagingError("CML returned invalid structural data") from None

    def _lab_ids(self) -> list[str]:
        payload = self._api("/api/v0/labs")
        if not isinstance(payload, list) or not all(
            isinstance(item, str) for item in payload
        ):
            raise StagingError("CML lab inventory is ambiguous")
        return payload

    def _lab(self, lab_id: str) -> dict[str, Any]:
        payload = self._api(f"/api/v0/labs/{lab_id}")
        if not isinstance(payload, dict):
            raise StagingError("CML lab inventory is ambiguous")
        return payload

    def _require_lab_stopped(self, lab_id: str, label: str) -> None:
        if lab_id not in self._lab_ids():
            return
        nodes = self._api(f"/api/v0/labs/{lab_id}/nodes")
        for node_id in nodes:
            node = self._api(f"/api/v0/labs/{lab_id}/nodes/{node_id}")
            if node.get("state") not in {"STOPPED", "DEFINED_ON_CORE"}:
                raise StagingError(f"{label} lab contains an active node")

    def admit(self) -> None:
        active_staging = []
        for lab_id in self._lab_ids():
            lab = self._lab(lab_id)
            title = lab.get("lab_title") or lab.get("title")
            if isinstance(title, str) and title.startswith("NCDP Staging "):
                active_staging.append((lab_id, title))
        if active_staging:
            raise StagingError("another NCDP staging realization exists")
        self._require_lab_stopped(LEGACY_LAB, "legacy")
        self._require_lab_stopped(SCRATCH_LAB, "scratch")
        for host in ("192.168.4.14", "192.168.4.20"):
            probe = subprocess.run(
                ["ping", "-c", "1", "-W", "1000", host],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if probe.returncode == 0:
                raise StagingError("fixed staging management address is already active")
        self._resolve_authority()
        if self._buildkite_context is not None:
            self.run_directory.parent.mkdir(mode=0o700, exist_ok=True)
            self.run_directory.parent.chmod(0o700)
        self.run_directory.mkdir(mode=0o700, parents=True)
        self.run_directory.chmod(0o700)
        self.data_directory.mkdir(mode=0o700)
        self._run_plain(
            [
                "terraform",
                f"-chdir={TERRAFORM_ROOT}",
                "init",
                "-input=false",
                "-lockfile=readonly",
                f"-backend-config=path={self.state_path}",
            ]
        )

    def _run_plain(self, command: list[str]) -> str:
        result = subprocess.run(
            command,
            env=self._terraform_env,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise StagingError("Terraform structural command failed")
        return result.stdout

    def _run_safe(self, arguments: list[str]) -> list[str]:
        terraform = subprocess.Popen(
            [
                "terraform",
                f"-chdir={TERRAFORM_ROOT}",
                *arguments,
                "-json",
                "-input=false",
            ],
            env=self._terraform_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        assert terraform.stdout is not None
        renderer = subprocess.run(
            [sys.executable, str(SAFE_UI)],
            stdin=terraform.stdout,
            text=True,
            capture_output=True,
            check=False,
        )
        terraform.stdout.close()
        terraform_code = terraform.wait()
        lines = renderer.stdout.splitlines()
        for line in lines:
            print(line, flush=True)
        if terraform_code or renderer.returncode:
            raise StagingError("safe Terraform operation failed")
        return lines

    @staticmethod
    def _changes(lines: list[str]) -> dict[str, str]:
        changes: dict[str, str] = {}
        pattern = re.compile(r"^planned resource=([^ ]+) action=([^ ]+)")
        for line in lines:
            match = pattern.match(line)
            if match:
                changes[match.group(1)] = match.group(2)
        return changes

    @staticmethod
    def _expected_addresses() -> set[str]:
        return (
            {"cml2_lab.twin", "module.twin.cml2_lifecycle.twin"}
            | {f"module.twin.cml2_node.{role}" for role in EXPECTED_NODES}
            | {f"module.twin.cml2_link.{role}" for role in EXPECTED_LINKS}
        )

    def create(self, evidence: StagingEvidence) -> None:
        plan = self._run_safe(["plan"])
        changes = self._changes(plan)
        if changes != dict.fromkeys(self._expected_addresses(), "create"):
            raise StagingError("Terraform create graph was not exactly 13 creates")
        self._run_safe(["apply", "-auto-approve"])
        self._managed = True
        self.state_path.chmod(0o600)
        self._outputs = json.loads(
            self._run_plain(
                ["terraform", f"-chdir={TERRAFORM_ROOT}", "output", "-json"]
            )
        )
        values = {key: value["value"] for key, value in self._outputs.items()}
        if (
            values.get("staging_run_id") != self.run_id
            or values.get("lab_title") != self.lab_title
            or set(values.get("node_ids", {})) != EXPECTED_NODES
            or set(values.get("link_ids", {})) != EXPECTED_LINKS
        ):
            raise StagingError("Terraform structural outputs are incomplete")
        evidence.lab_id = values["lab_id"]
        evidence.node_ids = values["node_ids"]
        evidence.link_ids = values["link_ids"]
        evidence.netbox_device_ids = {
            role: self._devices[role].inventory_object_id for role in self._devices
        }
        evidence.credential_references = {
            role: CachedSecrets.reference(self._devices[role]).reference
            for role in self._devices
        }
        if self._buildkite_context is not None:
            context = self._buildkite_context
            evidence.orchestrator = "buildkite"
            evidence.pipeline_id = context.pipeline_id
            evidence.build_id = context.build_id
            evidence.build_commit = context.commit
            evidence.build_branch = context.branch
            evidence.step_key = context.step_key
            evidence.job_id = context.job_id
        self._verify_creation(evidence)

    def _verify_creation(self, evidence: StagingEvidence) -> None:
        lab = self._lab(str(evidence.lab_id))
        if (lab.get("lab_title") or lab.get("title")) != self.lab_title:
            raise StagingError("created CML lab title mismatch")
        nodes = self._api(f"/api/v0/labs/{evidence.lab_id}/nodes")
        links = self._api(f"/api/v0/labs/{evidence.lab_id}/links")
        if set(nodes) != set(evidence.node_ids.values()) or set(links) != set(
            evidence.link_ids.values()
        ):
            raise StagingError("created CML topology identity mismatch")
        for node_id in nodes:
            node = self._api(f"/api/v0/labs/{evidence.lab_id}/nodes/{node_id}")
            if node.get("state") != "DEFINED_ON_CORE":
                raise StagingError("created CML node was not DEFINED_ON_CORE")
        self._verify_day0(evidence, "core_02", self._render_core())
        self._verify_day0(evidence, "edge_junos_01", self._render_edge())

    def _configuration(self, lab_id: str, node_id: str) -> str:
        for suffix in ("configuration", "configurations"):
            response = self._client.get(
                f"/api/v0/labs/{lab_id}/nodes/{node_id}/{suffix}"
            )
            if response.status_code == 200:
                payload = response.json()
                if isinstance(payload, str):
                    return payload
                if isinstance(payload, dict):
                    value = payload.get("configuration") or payload.get(
                        "config/juniper.conf"
                    )
                    if isinstance(value, str):
                        return value
        node = self._api(f"/api/v0/labs/{lab_id}/nodes/{node_id}")
        value = node.get("configuration")
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            contents = [
                item.get("content")
                for item in value
                if isinstance(item, dict) and isinstance(item.get("content"), str)
            ]
            if len(contents) == 1:
                return contents[0]
        raise StagingError("CML stored Day-0 configuration is unavailable")

    def _verify_day0(self, evidence: StagingEvidence, role: str, expected: str) -> None:
        stored = self._configuration(str(evidence.lab_id), evidence.node_ids[role])
        if (
            not stored
            or not expected
            or hashlib.sha256(stored.encode()).digest()
            != hashlib.sha256(expected.encode()).digest()
            or stored != expected
        ):
            raise StagingError(f"{role} stored Day-0 configuration mismatch")

    def _render_core(self) -> str:
        template = (
            ROOT / "infrastructure/cml/modules/twin/bootstrap/cat8000v.tftpl"
        ).read_text()
        values = {
            "hostname": "core-02",
            "management_ip": "192.168.4.14",
            "management_mask": "255.255.255.0",
            "username": self._credentials["core-02"].username,
            "password": self._credentials["core-02"].password,
        }
        for key, value in values.items():
            template = template.replace("${" + key + "}", value)
        return template

    def _render_edge(self) -> str:
        template = (
            ROOT / "infrastructure/cml/modules/twin/bootstrap/vjunos-router.tftpl"
        ).read_text()
        values = {
            "hostname": "edge-junos-01",
            "management_cidr": "192.168.4.20/24",
            "username": self._credentials["edge-junos-01"].username,
            "password_hash": self._terraform_env[
                "TF_VAR_edge_junos_01_bootstrap_password_hash"
            ],
        }
        for key, value in values.items():
            template = template.replace("${" + key + "}", value)
        return template

    def start(self, evidence: StagingEvidence) -> None:
        self._terraform_env["TF_VAR_twin_lifecycle_state"] = "STARTED"
        changes = self._changes(self._run_safe(["plan"]))
        if changes != {"module.twin.cml2_lifecycle.twin": "update"}:
            raise StagingError("Terraform STARTED graph was not lifecycle-only")
        self._run_safe(["apply", "-auto-approve"])
        if evidence.lab_id != self._outputs["lab_id"]["value"]:
            raise StagingError("CML realization identity changed during start")

    @staticmethod
    def _endpoint_ready(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except OSError:
            return False

    def _wait_device(self, host: str, timeout: int = 1200) -> float:
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            ping = (
                subprocess.run(
                    ["ping", "-c", "1", "-W", "1000", host],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                ).returncode
                == 0
            )
            arp = (
                subprocess.run(
                    ["arp", "-n", host],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                ).returncode
                == 0
            )
            if (
                arp
                and ping
                and self._endpoint_ready(host, 22)
                and self._endpoint_ready(host, 830)
            ):
                return round(time.monotonic() - started, 1)
            time.sleep(10)
        raise StagingError(f"{host} did not reach bounded management readiness")

    def _establish_host_trust(self, host: str, ports: tuple[int, ...]) -> None:
        known_hosts = self._known_hosts
        known_hosts.parent.mkdir(mode=0o700, exist_ok=True)
        for port in ports:
            query = host if port == 22 else f"[{host}]:{port}"
            subprocess.run(
                ["ssh-keygen", "-R", query, "-f", str(known_hosts)],
                capture_output=True,
                check=False,
            )
            scan = subprocess.run(
                ["ssh-keyscan", "-H", "-p", str(port), host],
                text=True,
                capture_output=True,
                check=True,
            ).stdout
            with known_hosts.open("a", encoding="utf-8") as stream:
                stream.write(scan)
        known_hosts.chmod(0o600)

    def validate(self, evidence: StagingEvidence) -> None:
        for role in ("core_02", "edge_junos_01"):
            device = self._devices[role]
            evidence.readiness_seconds[role] = self._wait_device(device.host)
            evidence.readiness_checks[role] = {
                "arp": "passed",
                "icmp": "passed",
                "tcp22": "passed",
                "tcp830": "passed",
            }
            self._establish_host_trust(
                device.host, (22, 830) if role == "edge_junos_01" else (22,)
            )
        evidence.readiness_outcome = "passed"
        cached = CachedSecrets(self._credentials)
        targets = {
            "core_02": (
                "GigabitEthernet2",
                AnsibleRunnerCiscoAdapter(ROOT, known_hosts=self._known_hosts),
            ),
            "edge_junos_01": (
                "ge-0/0/2",
                JunosPyEZAdapter(known_hosts=self._known_hosts),
            ),
        }
        if self._inventory is None:
            raise StagingError("staging inventory authority was not resolved")
        inventory = self._inventory
        for role, (interface, adapter) in targets.items():
            device = inventory.resolve(self._devices[role].name, interface)
            if device.inventory_object_id != self._devices[role].inventory_object_id:
                raise StagingError("fresh NetBox identity changed")
            intent = InterfaceDescriptionIntent(
                change_id=f"{self.run_id}-{role}-readonly",
                kind="interface_description",
                target=device.name,
                interface=interface,
                desired=DesiredDescription(
                    description="NCDP ephemeral staging validation"
                ),
            )
            try:
                plan_change(intent, inventory, cached, adapter)
            except ProviderError as error:
                evidence.ncdp_validation_outcome = "failed"
                raise StagingError(
                    f"{role} NCDP read-only validation failed: {error}"
                ) from None
            except Exception:
                evidence.ncdp_validation_outcome = "failed"
                raise StagingError(f"{role} NCDP read-only validation failed") from None
        evidence.ncdp_validation_outcome = "passed"

    def destroy(self, evidence: StagingEvidence) -> None:
        del evidence
        changes = self._changes(self._run_safe(["plan", "-destroy"]))
        if changes != dict.fromkeys(self._expected_addresses(), "delete"):
            raise StagingError("Terraform destroy graph was not exactly 13 destroys")
        self._run_safe(["destroy", "-auto-approve"])

    def verify_absent(self, evidence: StagingEvidence) -> None:
        if evidence.lab_id in self._lab_ids():
            raise StagingError("destroyed lab UUID remains present in CML")
        for lab_id in self._lab_ids():
            lab = self._lab(lab_id)
            title = lab.get("lab_title") or lab.get("title")
            if title == self.lab_title:
                raise StagingError("staging run title remains present in CML")
        if self._state_list():
            raise StagingError("Terraform state retains managed resources")

    def _state_list(self) -> list[str]:
        if not self.state_path.exists() or not self.data_directory.exists():
            return []
        return [
            line
            for line in self._run_plain(
                ["terraform", f"-chdir={TERRAFORM_ROOT}", "state", "list"]
            ).splitlines()
            if line
        ]

    def retire_state(self, evidence: StagingEvidence) -> None:
        del evidence
        resolved = self.run_directory.resolve()
        if resolved.name != self.run_id or resolved.parent.name != "ephemeral":
            raise StagingError("run directory retirement target is unsafe")
        shutil.rmtree(resolved)
        self._managed = False
        if resolved.exists():
            raise StagingError("run-scoped state retirement failed")

    def recover(self, evidence: StagingEvidence) -> None:
        """Destroy only a known retained run; never create or start resources."""
        if (
            not self.run_directory.is_dir()
            or self.run_directory.is_symlink()
            or not self.state_path.is_file()
            or not self.data_directory.is_dir()
        ):
            raise StagingError("retained staging run is unknown or incomplete")
        self._resolve_authority()
        self._run_plain(
            [
                "terraform",
                f"-chdir={TERRAFORM_ROOT}",
                "init",
                "-input=false",
                "-lockfile=readonly",
                f"-backend-config=path={self.state_path}",
            ]
        )
        addresses = set(self._state_list())
        validate_recovery_destroy_graph(
            addresses, self._expected_addresses(), dict.fromkeys(addresses, "delete")
        )
        values = {
            key: value["value"]
            for key, value in json.loads(
                self._run_plain(
                    ["terraform", f"-chdir={TERRAFORM_ROOT}", "output", "-json"]
                )
            ).items()
        }
        if (
            values.get("staging_run_id") != self.run_id
            or values.get("lab_title") != self.lab_title
        ):
            raise StagingError("retained staging output identity mismatch")
        evidence.lab_id = values.get("lab_id")
        evidence.node_ids = values.get("node_ids", {})
        evidence.link_ids = values.get("link_ids", {})
        changes = self._changes(self._run_safe(["plan", "-destroy"]))
        validate_recovery_destroy_graph(addresses, self._expected_addresses(), changes)
        self._managed = True
        self._run_safe(["destroy", "-auto-approve"])
        evidence.destroy_outcome = "passed"
        self.verify_absent(evidence)
        evidence.absence_verification_outcome = "passed"
        self.retire_state(evidence)
        evidence.state_retirement_outcome = "passed"
        evidence.overall_result = "passed"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-directory", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--identity", choices=("local", "buildkite"), default="local")
    return parser.parse_args()


def main() -> int:
    os.umask(0o077)
    args = parse_args()
    try:
        buildkite_context = None
        buildkite_jwt = None
        if args.identity == "buildkite":
            for name in ("NCDP_OPENBAO_ROLE_ID", "NCDP_OPENBAO_SECRET_ID"):
                if os.environ.get(name):
                    raise StagingError(
                        "ambient AppRole is prohibited in Buildkite staging"
                    )
            buildkite_context = staging_context_from_environment()
            if args.run_id != buildkite_context.staging_run_id:
                raise StagingError("Buildkite staging run identity mismatch")
            state_root_value = os.environ.get("NCDP_STAGING_STATE_ROOT", "")
            if not state_root_value:
                raise StagingError("Buildkite staging state root is missing")
            state_root = validate_staging_state_root(Path(state_root_value), ROOT)
            expected_run_directory = (
                state_root / "ephemeral" / buildkite_context.staging_run_id
            )
            if args.run_directory.resolve() != expected_run_directory:
                raise StagingError("Buildkite staging run directory mismatch")
            buildkite_jwt = read_buildkite_oidc_jwt(sys.stdin)
        validate_run_directory(args.run_id, args.run_directory)
        operations = LocalOperations(
            args.run_id,
            args.run_directory,
            buildkite_context=buildkite_context,
            buildkite_jwt=buildkite_jwt,
        )
        initial_evidence = None
        if buildkite_context is not None:
            initial_evidence = StagingEvidence(
                schema_version="2",
                staging_run_id=args.run_id,
                orchestrator="buildkite",
                pipeline_id=buildkite_context.pipeline_id,
                build_id=buildkite_context.build_id,
                build_commit=buildkite_context.commit,
                build_branch=buildkite_context.branch,
                step_key=buildkite_context.step_key,
                job_id=buildkite_context.job_id,
            )
        evidence = run_staging_lifecycle(
            args.run_id,
            args.run_directory,
            operations,
            evidence=initial_evidence,
        )
    except Exception as error:
        print(f"ephemeral staging admission failed: {error}", file=sys.stderr)
        return 1
    payload = json.dumps(evidence.safe_dict(), indent=2, sort_keys=True) + "\n"
    args.evidence.write_text(payload, encoding="utf-8")
    args.evidence.chmod(0o600)
    print(payload, end="")
    return 0 if evidence.overall_result == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
