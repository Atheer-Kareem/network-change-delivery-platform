"""CML scope admission and profile-required bounded disposable-node recycling."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import ssl
import subprocess
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from pydantic import TypeAdapter

from network_change_delivery.architecture_contracts import (
    CML_REALIZATION_PROFILE_CATALOG,
    CmlBootPolicy,
    CmlRealizationProfileID,
)
from network_change_delivery.profile_inventory import (
    STAGING_REALIZATION_SCOPE,
    ProfiledInventoryDevice,
    ProfiledPopulationScope,
)
from network_change_delivery.profiled_realization import EvidenceReference, StagingRunID
from network_change_delivery.profiled_staging import (
    CURRENT_STAGING_TOPOLOGY,
    ProfiledStagingAmbiguousError,
    ProfiledStagingError,
    ProfiledStagingTopology,
    record_staging_duration,
    staging_interface_name,
    staging_management_slot,
    validate_management_only_bootstrap,
    validate_staging_management_links,
)

STAGING_TITLE_PREFIX = "NCDP Staging"


@dataclass(frozen=True)
class ObservedStagingRealization:
    """Secret-free independently observed CML identity and topology facts."""

    lab_id: str
    lab_title: str
    node_ids: dict[str, str]
    link_ids: dict[str, str]
    topology_evidence: EvidenceReference
    cml_anchors: dict[str, EvidenceReference]
    topology: ProfiledStagingTopology = CURRENT_STAGING_TOPOLOGY


class ProfiledStagingCmlReader:
    """Narrow authenticated GET-only client; it has no CML mutation methods."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    @classmethod
    def from_environment(cls, *, token: str | None = None) -> ProfiledStagingCmlReader:
        address = os.environ.get("CML2_ADDRESS")
        token = os.environ.get("CML2_TOKEN") if token is None else token
        certificate = os.environ.get("CML2_CACERT")
        if not address or not token or not certificate:
            raise ProfiledStagingError("profiled staging CML read authority missing")
        try:
            context = ssl.create_default_context(cadata=certificate)
        except ssl.SSLError:
            raise ProfiledStagingError(
                "profiled staging CML TLS authority rejected"
            ) from None
        return cls(
            httpx.Client(
                base_url=address.rstrip("/"),
                headers={"Authorization": f"Bearer {token}"},
                verify=context,
                timeout=15,
                trust_env=False,
                follow_redirects=False,
            )
        )

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, *, allow_missing: bool = False) -> Any:
        try:
            response = self._client.get(path)
        except httpx.HTTPError:
            raise ProfiledStagingError(
                "profiled staging CML observation failed"
            ) from None
        if allow_missing and response.status_code == 404:
            return None
        if response.status_code != 200:
            raise ProfiledStagingError("profiled staging CML observation rejected")
        try:
            return response.json()
        except ValueError:
            raise ProfiledStagingError(
                "profiled staging CML response rejected"
            ) from None

    def lab_ids(self) -> tuple[str, ...]:
        value = self._get("/api/v0/labs")
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise ProfiledStagingError("profiled staging CML lab population rejected")
        return tuple(value)

    def lab(
        self, lab_id: str, *, allow_missing: bool = False
    ) -> dict[str, object] | None:
        value = self._get(f"/api/v0/labs/{lab_id}", allow_missing=allow_missing)
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ProfiledStagingError("profiled staging CML lab rejected")
        return value

    def ids(self, lab_id: str, kind: str) -> tuple[str, ...]:
        value = self._get(f"/api/v0/labs/{lab_id}/{kind}")
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise ProfiledStagingError(f"profiled staging CML {kind} rejected")
        return tuple(value)

    def item(self, lab_id: str, kind: str, identity: str) -> dict[str, object]:
        value = self._get(f"/api/v0/labs/{lab_id}/{kind}/{identity}")
        if not isinstance(value, dict):
            raise ProfiledStagingError(f"profiled staging CML {kind} identity rejected")
        return value

    def interfaces(self, lab_id: str, node_id: str) -> dict[int, str]:
        identities = self._get(f"/api/v0/labs/{lab_id}/nodes/{node_id}/interfaces")
        if not isinstance(identities, list):
            raise ProfiledStagingError("profiled staging CML interfaces rejected")
        result: dict[int, str] = {}
        for identity in identities:
            if not isinstance(identity, str):
                raise ProfiledStagingError("profiled staging CML interface rejected")
            item = self.item(lab_id, "interfaces", identity)
            slot = item.get("slot")
            if slot is None:
                continue
            if (
                isinstance(slot, bool)
                or not isinstance(slot, int)
                or slot < 0
                or slot in result
            ):
                raise ProfiledStagingError(
                    "profiled staging CML interface slot rejected"
                )
            result[slot] = identity
        return result

    def configuration(self, lab_id: str, node_id: str) -> str:
        for suffix in ("configuration", "configurations"):
            try:
                response = self._client.get(
                    f"/api/v0/labs/{lab_id}/nodes/{node_id}/{suffix}"
                )
            except httpx.HTTPError:
                raise ProfiledStagingError(
                    "profiled staging CML observation failed"
                ) from None
            if response.status_code in (404, 405):
                continue
            if response.status_code != 200:
                raise ProfiledStagingError("profiled staging CML observation rejected")
            try:
                value = response.json()
            except ValueError:
                continue
            if isinstance(value, str):
                return value
            if isinstance(value, dict) and isinstance(value.get("configuration"), str):
                return value["configuration"]
        node = self.item(lab_id, "nodes", node_id)
        value = node.get("configuration")
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            values = [item.get("content") for item in value if isinstance(item, dict)]
            if len(values) == 1 and isinstance(values[0], str):
                return values[0]
        raise ProfiledStagingError("profiled staging stored Day-0 unavailable")


class ProfiledStagingCmlLabStarter:
    """One admitted initial LAB START; never node/link START or mutation retry."""

    _ACTIVE = frozenset({"QUEUED", "STARTED", "STARTING", "BOOTING", "BOOTED"})

    def __init__(self, client: httpx.Client) -> None:
        self._client = client
        self._reader = ProfiledStagingCmlReader(client)
        self._attempted = False

    @classmethod
    def from_environment(
        cls, *, token: str | None = None
    ) -> ProfiledStagingCmlLabStarter:
        address = os.environ.get("CML2_ADDRESS")
        token = os.environ.get("CML2_TOKEN") if token is None else token
        certificate = os.environ.get("CML2_CACERT")
        if not address or not token or not certificate:
            raise ProfiledStagingError(
                "profiled staging CML lab start authority missing"
            )
        try:
            context = ssl.create_default_context(cadata=certificate)
        except ssl.SSLError:
            raise ProfiledStagingError(
                "profiled staging CML lab start TLS rejected"
            ) from None
        return cls(
            httpx.Client(
                base_url=address.rstrip("/"),
                headers={"Authorization": f"Bearer {token}"},
                verify=context,
                timeout=15,
                trust_env=False,
                follow_redirects=False,
            )
        )

    def close(self) -> None:
        self._client.close()

    def _observe(
        self,
        run_id: str,
        observed: ObservedStagingRealization,
        devices: tuple[ProfiledInventoryDevice, ...],
        *,
        initial: bool,
    ) -> dict[str, object]:
        """One bounded exact identity/state readback; no discovery or polling."""
        lab = self._reader.lab(observed.lab_id)
        if (
            not lab
            or lab.get("id") != observed.lab_id
            or (lab.get("lab_title") or lab.get("title")) != f"NCDP Staging {run_id}"
        ):
            raise ProfiledStagingError("profiled staging lab start lab rejected")
        node_ids = self._reader.ids(observed.lab_id, "nodes")
        link_ids = self._reader.ids(observed.lab_id, "links")
        if (
            len(node_ids) != len(observed.node_ids)
            or set(node_ids) != set(observed.node_ids.values())
            or len(link_ids) != len(observed.link_ids)
            or set(link_ids) != set(observed.link_ids.values())
        ):
            raise ProfiledStagingError(
                "profiled staging lab start realization rejected"
            )
        expected = {
            "system_bridge": ("system-bridge", "external_connector", None),
            "management_switch": ("management-switch", "unmanaged_switch", None),
        }
        for device in devices:
            profile = CML_REALIZATION_PROFILE_CATALOG[
                device.effective_staging_cml_realization_profile_id
            ]
            expected[str(device.logical_name).replace("-", "_")] = (
                str(device.logical_name),
                profile.node_definition,
                profile.image_definition,
            )
        states = {}
        for key, (label, definition, image) in expected.items():
            node = self._reader.item(observed.lab_id, "nodes", observed.node_ids[key])
            if (
                node.get("id") != observed.node_ids[key]
                or node.get("label") != label
                or node.get("node_definition") != definition
                or (
                    image is not None
                    and (
                        node.get("image_definition") or node.get("image_definition_id")
                    )
                    != image
                )
            ):
                raise ProfiledStagingError("profiled staging lab start node rejected")
            states[key] = node.get("state")
        allowed = {"DEFINED_ON_CORE"} if initial else {"DEFINED_ON_CORE"} | self._ACTIVE
        if (
            not isinstance(lab.get("state"), str)
            or lab["state"] not in allowed
            or any(
                not isinstance(state, str) or state not in allowed
                for state in states.values()
            )
        ):
            raise ProfiledStagingError("profiled staging lab start state rejected")
        if not initial and not (
            lab.get("state") in self._ACTIVE
            or any(state in self._ACTIVE for state in states.values())
        ):
            raise ProfiledStagingError("profiled staging lab start not observed")
        return {"lab_state": lab["state"], "node_states": states}

    def start(
        self,
        *,
        run_id: str,
        observed: ObservedStagingRealization,
        devices: tuple[ProfiledInventoryDevice, ...],
    ) -> EvidenceReference:
        if self._attempted:
            raise ProfiledStagingError("profiled staging lab START cannot be replayed")
        self._attempted = True
        try:
            TypeAdapter(StagingRunID).validate_python(run_id)
            if str(UUID(observed.lab_id)) != observed.lab_id:
                raise ValueError
        except ValueError:
            raise ProfiledStagingError(
                "profiled staging lab start identity rejected"
            ) from None
        try:
            observed.topology.scope.require_bindings(devices)
        except ValueError:
            raise ProfiledStagingError(
                "profiled staging lab start population rejected"
            ) from None
        links = staging_link_slots(devices, observed.topology)
        if (
            observed.lab_title != f"NCDP Staging {run_id}"
            or observed.topology_evidence.identity != f"staging-topology:{run_id}"
            or set(observed.node_ids)
            != {
                "system_bridge",
                "management_switch",
                *(str(device.logical_name).replace("-", "_") for device in devices),
            }
            or len(set(observed.node_ids.values())) != len(devices) + 2
            or set(observed.link_ids) != set(links)
            or len(set(observed.link_ids.values())) != len(links)
            or any(
                observed.cml_anchors.get(str(device.logical_name))
                != EvidenceReference(
                    identity=f"cml-anchor:{observed.lab_id}:"
                    + observed.node_ids[str(device.logical_name).replace("-", "_")],
                    digest=observed.topology_evidence.digest,
                )
                for device in devices
            )
        ):
            raise ProfiledStagingError(
                "profiled staging lab start realization rejected"
            )
        self._observe(run_id, observed, devices, initial=True)
        # gocmlclient v0.2.5 Lab.Start: current endpoint, legacy only on 404.
        # No alternative after transport/408/5xx uncertainty; no node/link loop.
        response = None
        try:
            response = self._client.put(f"/api/v0/labs/{observed.lab_id}/start")
            if response.status_code == 404:
                response = self._client.put(
                    f"/api/v0/labs/{observed.lab_id}/state/start"
                )
        except httpx.HTTPError:
            response = None
        facts: dict[str, object] = {"outcome": "acknowledged"}
        if (
            response is None
            or response.status_code == 408
            or response.status_code >= 500
        ):
            try:
                facts = self._observe(run_id, observed, devices, initial=False)
            except ProfiledStagingError:
                raise ProfiledStagingAmbiguousError(
                    "profiled staging CML lab start outcome is ambiguous"
                ) from None
        elif response.status_code not in {200, 204}:
            raise ProfiledStagingError("profiled staging CML lab start rejected")
        facts.update(
            run_id=run_id,
            lab_id=observed.lab_id,
            nodes=observed.node_ids,
            topology_digest=observed.topology_evidence.digest,
        )
        digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(facts, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        return EvidenceReference(identity=f"staging-lab-start:{run_id}", digest=digest)


class ProfiledStagingCmlProfileRecycler:
    """One exact run-scoped CML recycle boundary selected by realization policy."""

    _FIRST_BOOT_PERSISTENCE_SECONDS = 60
    _STOP_TIMEOUT_SECONDS = 180
    _START_TIMEOUT_SECONDS = 300
    _POLL_SECONDS = 2

    def __init__(self, client: httpx.Client) -> None:
        self._client = client
        self.timings_seconds: dict[str, float] = {}

    @classmethod
    def from_environment(
        cls, *, token: str | None = None
    ) -> ProfiledStagingCmlProfileRecycler:
        address = os.environ.get("CML2_ADDRESS")
        token = os.environ.get("CML2_TOKEN") if token is None else token
        certificate = os.environ.get("CML2_CACERT")

        if not address or not token or not certificate:
            raise ProfiledStagingError("profiled staging CML recycle authority missing")

        try:
            context = ssl.create_default_context(cadata=certificate)
        except ssl.SSLError:
            raise ProfiledStagingError(
                "profiled staging CML recycle TLS authority rejected"
            ) from None

        return cls(
            httpx.Client(
                base_url=address.rstrip("/"),
                headers={"Authorization": f"Bearer {token}"},
                verify=context,
                timeout=15,
                trust_env=False,
                follow_redirects=False,
            )
        )

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str) -> dict[str, object]:
        try:
            response = self._client.get(path)
        except httpx.HTTPError:
            raise ProfiledStagingError(
                "profiled staging CML recycle observation failed"
            ) from None

        if response.status_code != 200:
            raise ProfiledStagingError(
                "profiled staging CML recycle observation rejected"
            )

        try:
            value = response.json()
        except ValueError:
            raise ProfiledStagingError(
                "profiled staging CML recycle response rejected"
            ) from None

        if not isinstance(value, dict):
            raise ProfiledStagingError("profiled staging CML recycle response rejected")

        return value

    def _lab(self, lab_id: str) -> dict[str, object]:
        return self._get(f"/api/v0/labs/{lab_id}")

    def _node(self, lab_id: str, node_id: str) -> dict[str, object]:
        return self._get(f"/api/v0/labs/{lab_id}/nodes/{node_id}")

    def _admit_profile_node(
        self,
        *,
        run_id: str,
        lab_id: str,
        node_id: str,
        device: ProfiledInventoryDevice,
        required_state: str | frozenset[str],
    ) -> str:
        lab = self._lab(lab_id)
        title = lab.get("lab_title") or lab.get("title")

        if title != f"NCDP Staging {run_id}":
            raise ProfiledStagingError("profiled staging profile recycle lab rejected")

        if (
            CML_REALIZATION_PROFILE_CATALOG[
                device.effective_staging_cml_realization_profile_id
            ].boot_policy
            != CmlBootPolicy.IOSV_PERSISTENCE_RECYCLE
        ):
            raise ProfiledStagingError(
                "profiled staging profile recycle profile rejected"
            )

        profile = CML_REALIZATION_PROFILE_CATALOG[
            device.effective_staging_cml_realization_profile_id
        ]

        node = self._node(lab_id, node_id)
        image = node.get("image_definition") or node.get("image_definition_id")

        if (
            node.get("label") != str(device.logical_name)
            or node.get("node_definition") != profile.node_definition
            or image != profile.image_definition
        ):
            raise ProfiledStagingError(
                "profiled staging profile recycle identity rejected"
            )

        state = node.get("state")

        accepted = (
            frozenset({required_state})
            if isinstance(required_state, str)
            else required_state
        )
        if not isinstance(state, str) or state not in accepted:
            raise ProfiledStagingError(
                "profiled staging profile recycle state rejected"
            )

        return state

    def _wait_first_boot(
        self,
        *,
        run_id: str,
        lab_id: str,
        node_id: str,
        device: ProfiledInventoryDevice,
    ) -> None:
        # Initial Terraform START is non-blocking. Admit the exact transit
        # on every observation; unknown/stopped states never grant a recycle.
        deadline = time.monotonic() + self._START_TIMEOUT_SECONDS
        while True:
            state = self._admit_profile_node(
                run_id=run_id,
                lab_id=lab_id,
                node_id=node_id,
                device=device,
                required_state=frozenset(
                    {
                        "DEFINED_ON_CORE",
                        "QUEUED",
                        "STARTED",
                        "STARTING",
                        "BOOTING",
                        "BOOTED",
                    }
                ),
            )
            if state == "BOOTED":
                return
            if time.monotonic() >= deadline:
                raise ProfiledStagingError(
                    "profiled staging transit first boot timed out"
                )
            time.sleep(self._POLL_SECONDS)

    def _put_state_once(
        self,
        *,
        lab_id: str,
        node_id: str,
        action: str,
        reconciled_states: frozenset[str],
    ) -> None:
        path = f"/api/v0/labs/{lab_id}/nodes/{node_id}/state/{action}"

        try:
            response = self._client.put(path)
        except httpx.HTTPError:
            try:
                state = self._node(lab_id, node_id).get("state")
            except ProfiledStagingError:
                raise ProfiledStagingAmbiguousError(
                    f"profiled staging transit {action} outcome is ambiguous"
                ) from None

            if state not in reconciled_states:
                raise ProfiledStagingAmbiguousError(
                    f"profiled staging transit {action} outcome is ambiguous"
                ) from None

            return

        if response.status_code in {200, 204}:
            return

        # A server-side failure or request timeout response can be returned
        # after the mutation crossed the boundary. Reconcile once through
        # independent GET-only observation and never replay the PUT.
        if response.status_code >= 500 or response.status_code == 408:
            try:
                state = self._node(lab_id, node_id).get("state")
            except ProfiledStagingError:
                raise ProfiledStagingAmbiguousError(
                    f"profiled staging transit {action} outcome is ambiguous"
                ) from None

            if state in reconciled_states:
                return

            raise ProfiledStagingAmbiguousError(
                f"profiled staging transit {action} outcome is ambiguous"
            )

        raise ProfiledStagingError(f"profiled staging transit {action} rejected")

    def _wait_for_state(
        self,
        *,
        lab_id: str,
        node_id: str,
        expected: str,
        timeout_seconds: int,
    ) -> str:
        deadline = time.monotonic() + timeout_seconds

        while True:
            try:
                state = self._node(lab_id, node_id).get("state")
            except ProfiledStagingError:
                raise ProfiledStagingAmbiguousError(
                    "profiled staging profile recycle completion is ambiguous"
                ) from None

            if state == expected:
                return expected

            if time.monotonic() >= deadline:
                raise ProfiledStagingAmbiguousError(
                    "profiled staging profile recycle completion is ambiguous"
                )

            time.sleep(self._POLL_SECONDS)

    def recycle(
        self,
        *,
        run_id: str,
        observed: ObservedStagingRealization,
        device: ProfiledInventoryDevice,
    ) -> EvidenceReference:
        """Recycle the exact scoped subject once under its reviewed boot policy."""
        member = observed.topology.scope.member(device.logical_name)
        if member not in observed.topology.scope.members or (
            member.device_identity != device.device_identity
            or member.automation_profile_id != device.automation_profile_id
            or (
                member.staging_cml_realization_profile_id
                or member.cml_realization_profile_id
            )
            != device.effective_staging_cml_realization_profile_id
            or CML_REALIZATION_PROFILE_CATALOG[
                device.effective_staging_cml_realization_profile_id
            ].boot_policy
            != CmlBootPolicy.IOSV_PERSISTENCE_RECYCLE
        ):
            raise ProfiledStagingError("profiled staging recycle scope rejected")
        if observed.lab_title != f"NCDP Staging {run_id}":
            raise ProfiledStagingError("profiled staging recycle realization rejected")
        node_id = observed.node_ids.get(device.logical_name.replace("-", "_"))
        if not isinstance(node_id, str) or not node_id:
            raise ProfiledStagingError("profiled staging recycle node rejected")
        subject = device

        # Observe subject independently of the other nodes' initial boot.
        with record_staging_duration(self.timings_seconds, "recycle_first_boot"):
            self._wait_first_boot(
                run_id=run_id,
                lab_id=observed.lab_id,
                node_id=node_id,
                device=subject,
            )

        # Real IOSv diagnosis established that CML Day-0 reaches
        # persistent startup configuration after first boot while
        # legacy AutoInstall/DHCP can still own the running interface.
        # STARTED alone does not prove persistence. Start the accepted interval
        # at this node's first observed BOOTED, not whole-lab convergence.
        # Give that first boot one bounded persistence interval before
        # recycling only this already-admitted disposable node.
        with record_staging_duration(self.timings_seconds, "recycle_persistence"):
            time.sleep(self._FIRST_BOOT_PERSISTENCE_SECONDS)

        self._admit_profile_node(
            run_id=run_id,
            lab_id=observed.lab_id,
            node_id=node_id,
            device=subject,
            required_state="BOOTED",
        )

        # Exactly one STOP request. No blind retry.
        with record_staging_duration(self.timings_seconds, "recycle_stop"):
            self._put_state_once(
                lab_id=observed.lab_id,
                node_id=node_id,
                action="stop",
                reconciled_states=frozenset({"STOPPED"}),
            )

            stopped = self._wait_for_state(
                lab_id=observed.lab_id,
                node_id=node_id,
                expected="STOPPED",
                timeout_seconds=self._STOP_TIMEOUT_SECONDS,
            )

        self._admit_profile_node(
            run_id=run_id,
            lab_id=observed.lab_id,
            node_id=node_id,
            device=subject,
            required_state="STOPPED",
        )

        # Exactly one START request. No blind retry.
        with record_staging_duration(self.timings_seconds, "recycle_second_boot"):
            self._put_state_once(
                lab_id=observed.lab_id,
                node_id=node_id,
                action="start",
                reconciled_states=frozenset(
                    {"QUEUED", "STARTED", "STARTING", "BOOTING", "BOOTED"}
                ),
            )

            booted = self._wait_for_state(
                lab_id=observed.lab_id,
                node_id=node_id,
                expected="BOOTED",
                timeout_seconds=self._START_TIMEOUT_SECONDS,
            )

        self._admit_profile_node(
            run_id=run_id,
            lab_id=observed.lab_id,
            node_id=node_id,
            device=subject,
            required_state="BOOTED",
        )

        facts = {
            "run_id": run_id,
            "lab_id": observed.lab_id,
            "node_id": node_id,
            "device_identity": subject.device_identity,
            "logical_name": str(subject.logical_name),
            "cml_realization_profile_id": (
                subject.effective_staging_cml_realization_profile_id
            ),
            "first_boot_persistence_seconds": (self._FIRST_BOOT_PERSISTENCE_SECONDS),
            "stop_state": stopped,
            "start_state": booted,
            "timings_seconds": self.timings_seconds,
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

        return EvidenceReference(
            identity=f"staging-profile-recycle:{run_id}:{device.logical_name}",
            digest=digest,
        )


def _icmp_address_is_active(address: str, *, timeout: float) -> bool:
    """Return only a positive bounded ICMP observation as address occupancy."""
    try:
        result = subprocess.run(
            ("ping", "-n", "-c", "1", address),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def admit_no_staging_collision(
    reader: ProfiledStagingCmlReader,
    devices: tuple[ProfiledInventoryDevice, ...],
    *,
    probe_timeout: float = 0.5,
    scope: ProfiledPopulationScope = STAGING_REALIZATION_SCOPE,
) -> None:
    """Reject an existing staging lab or occupied admitted management endpoint."""
    scope.require_bindings(devices)
    for lab_id in reader.lab_ids():
        lab = reader.lab(lab_id)
        title = (lab or {}).get("lab_title") or (lab or {}).get("title")
        if isinstance(title, str) and title.startswith(STAGING_TITLE_PREFIX):
            raise ProfiledStagingError("existing NCDP Staging lab rejected")
    for device in devices:
        endpoint = device.management_endpoints.staging.binding.l3_endpoint
        if _icmp_address_is_active(str(endpoint.address.ip), timeout=probe_timeout):
            raise ProfiledStagingError(
                "profiled staging management endpoint is occupied"
            )
        for port in {22, 830, endpoint.port}:
            try:
                connection = socket.create_connection(
                    (str(endpoint.address.ip), port), timeout=probe_timeout
                )
            except OSError:
                continue
            connection.close()
            raise ProfiledStagingError(
                "profiled staging management endpoint is occupied"
            )


def staging_link_slots(devices, topology: ProfiledStagingTopology):
    """Resolve exact admitted topology and management slots before CML comparison."""
    validate_staging_management_links(devices, topology)
    links = {
        "system_bridge_management": (("system_bridge", 0), ("management_switch", 0))
    }
    for index, device in enumerate(devices):
        key = device.logical_name.replace("-", "_")
        slot = staging_management_slot(device)
        links[f"management_{key}"] = (("management_switch", index + 1), (key, slot))
    for key, link in topology.terraform_links().items():
        links[key] = (
            (link["node_a"], link["slot_a"]),
            (link["node_b"], link["slot_b"]),
        )
    return links


def admit_created_realization(
    reader: ProfiledStagingCmlReader,
    run_id: str,
    outputs: dict[str, object],
    devices: tuple[ProfiledInventoryDevice, ...],
    *,
    topology: ProfiledStagingTopology = CURRENT_STAGING_TOPOLOGY,
) -> ObservedStagingRealization:
    """Independently bind Terraform outputs to actual CML GET observations."""
    links = staging_link_slots(devices, topology)
    lab_id = outputs.get("lab_id")
    node_ids = outputs.get("node_ids")
    link_ids = outputs.get("link_ids")
    title = f"NCDP Staging {run_id}"
    if (
        not isinstance(lab_id, str)
        or not isinstance(node_ids, dict)
        or not isinstance(link_ids, dict)
    ):
        raise ProfiledStagingError("profiled staging output identity rejected")
    expected_node_keys = {
        "system_bridge",
        "management_switch",
        *(device.logical_name.replace("-", "_") for device in devices),
    }
    if set(node_ids) != expected_node_keys or set(link_ids) != set(links):
        raise ProfiledStagingError("profiled staging output population rejected")
    if not all(
        isinstance(value, str) and value
        for value in (*node_ids.values(), *link_ids.values())
    ):
        raise ProfiledStagingError("profiled staging output identity rejected")
    lab = reader.lab(lab_id)
    if (lab or {}).get("lab_title") != title and (lab or {}).get("title") != title:
        raise ProfiledStagingError("profiled staging observed lab rejected")
    actual_nodes = set(reader.ids(lab_id, "nodes"))
    actual_links = set(reader.ids(lab_id, "links"))
    if len(actual_nodes) != len(devices) + 2 or actual_nodes != set(node_ids.values()):
        raise ProfiledStagingError("profiled staging observed node population rejected")
    if len(actual_links) != len(links) or actual_links != set(link_ids.values()):
        raise ProfiledStagingError("profiled staging observed link population rejected")

    for key, label, definition in (
        ("system_bridge", "system-bridge", "external_connector"),
        ("management_switch", "management-switch", "unmanaged_switch"),
    ):
        node = reader.item(lab_id, "nodes", str(node_ids[key]))
        if node.get("label") != label or node.get("node_definition") != definition:
            raise ProfiledStagingError(
                "profiled staging observed infrastructure node rejected"
            )

    by_key = {str(device.logical_name).replace("-", "_"): device for device in devices}
    for key, device in by_key.items():
        node = reader.item(lab_id, "nodes", str(node_ids[key]))
        profile = CML_REALIZATION_PROFILE_CATALOG[
            device.effective_staging_cml_realization_profile_id
        ]
        image = node.get("image_definition") or node.get("image_definition_id")
        if (
            node.get("label") != str(device.logical_name)
            or node.get("node_definition") != profile.node_definition
            or image != profile.image_definition
        ):
            raise ProfiledStagingError(
                "profiled staging observed node profile rejected"
            )
        configuration = reader.configuration(lab_id, str(node_ids[key]))
        validate_management_only_bootstrap(configuration)
        endpoint = device.management_endpoints.staging.binding.l3_endpoint
        management_marker = staging_interface_name(
            device,
            device.management_endpoints.staging.binding.l3_endpoint.interface.name,
        )
        if (
            device.effective_staging_cml_realization_profile_id
            != CmlRealizationProfileID.VJUNOS_ROUTER_23_2R1_15
        ):
            management_marker = "interface " + management_marker
        if (
            str(device.expected_hostname) not in configuration
            or str(endpoint.address.ip) not in configuration
            or management_marker not in configuration
            or (
                device.effective_staging_cml_realization_profile_id
                == CmlRealizationProfileID.IOSVL2_2020
                and " no switchport" not in configuration
            )
        ):
            raise ProfiledStagingError("profiled staging observed Day-0 rejected")

    slots = {
        key: reader.interfaces(lab_id, str(identity))
        for key, identity in node_ids.items()
    }
    for key, device in by_key.items():
        catalog_slots = {
            item.cml_slot
            for item in CML_REALIZATION_PROFILE_CATALOG[
                device.effective_staging_cml_realization_profile_id
            ].physical_interface_slots
        }
        if not catalog_slots.issubset(slots[key]):
            raise ProfiledStagingError(
                "profiled staging observed device slots rejected"
            )
    observed_links: dict[str, tuple[str, str]] = {}
    for key, ((left_node, left_slot), (right_node, right_slot)) in links.items():
        link = reader.item(lab_id, "links", str(link_ids[key]))
        actual = {str(link.get("interface_a")), str(link.get("interface_b"))}
        try:
            expected = {slots[left_node][left_slot], slots[right_node][right_slot]}
        except KeyError:
            raise ProfiledStagingError(
                "profiled staging observed link slot rejected"
            ) from None
        if actual != expected:
            raise ProfiledStagingError(
                "profiled staging observed link topology rejected"
            )
        observed_links[key] = tuple(sorted(actual))  # type: ignore[assignment]

    facts = {
        "run_id": run_id,
        "lab_id": lab_id,
        "nodes": node_ids,
        "links": link_ids,
        "endpoints": observed_links,
        "devices": {
            key: {
                "identity": device.device_identity,
                "automation_profile": device.automation_profile_id,
                "cml_profile": device.effective_staging_cml_realization_profile_id,
            }
            for key, device in by_key.items()
        },
    }
    digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                facts, sort_keys=True, separators=(",", ":"), default=str
            ).encode()
        ).hexdigest()
    )
    topology_evidence = EvidenceReference(
        identity=f"staging-topology:{run_id}", digest=digest
    )
    anchors = {
        str(device.logical_name): EvidenceReference(
            identity=f"cml-anchor:{lab_id}:{node_ids[key]}", digest=digest
        )
        for key, device in by_key.items()
    }
    return ObservedStagingRealization(
        lab_id=lab_id,
        lab_title=title,
        node_ids={key: str(value) for key, value in node_ids.items()},
        link_ids={key: str(value) for key, value in link_ids.items()},
        topology_evidence=topology_evidence,
        topology=topology,
        cml_anchors=anchors,
    )
