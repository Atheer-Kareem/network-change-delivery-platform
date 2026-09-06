"""CML admission plus one narrowly fenced transit-IOSv recycle boundary."""

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

import httpx

from network_change_delivery.architecture_contracts import (
    CML_REALIZATION_PROFILE_CATALOG,
    CmlRealizationProfileID,
)
from network_change_delivery.profile_inventory import ProfiledInventoryDevice
from network_change_delivery.profiled_realization import EvidenceReference
from network_change_delivery.profiled_staging import (
    PROFILED_STAGING_DEVICE_NAMES,
    PROFILED_STAGING_LINK_COUNT,
    PROFILED_STAGING_NODE_COUNT,
    ProfiledStagingAmbiguousError,
    ProfiledStagingError,
    validate_management_only_bootstrap,
)

STAGING_TITLE_PREFIX = "NCDP Staging"
STAGING_MANAGEMENT_ADDRESSES = {
    "core-02": "192.168.4.30",
    "edge-junos-01": "192.168.4.40",
    "transit-ios-01": "192.168.4.31",
    "access-sw-01": "192.168.4.32",
}


@dataclass(frozen=True)
class ObservedStagingRealization:
    """Secret-free independently observed CML identity and topology facts."""

    lab_id: str
    lab_title: str
    node_ids: dict[str, str]
    link_ids: dict[str, str]
    topology_evidence: EvidenceReference
    cml_anchors: dict[str, EvidenceReference]


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


class ProfiledStagingCmlTransitRecycler:
    """One exact run-scoped CML recycle boundary for transit IOSv only."""

    _FIRST_BOOT_PERSISTENCE_SECONDS = 60
    _STOP_TIMEOUT_SECONDS = 180
    _START_TIMEOUT_SECONDS = 300
    _POLL_SECONDS = 2

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    @classmethod
    def from_environment(
        cls, *, token: str | None = None
    ) -> ProfiledStagingCmlTransitRecycler:
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

    def _admit_exact_transit(
        self,
        *,
        run_id: str,
        lab_id: str,
        node_id: str,
        device: ProfiledInventoryDevice,
        required_state: str,
    ) -> str:
        lab = self._lab(lab_id)
        title = lab.get("lab_title") or lab.get("title")

        if title != f"NCDP Staging {run_id}":
            raise ProfiledStagingError("profiled staging transit recycle lab rejected")

        if (
            str(device.logical_name) != "transit-ios-01"
            or device.cml_realization_profile_id
            != CmlRealizationProfileID.IOSV_159_3_M12
        ):
            raise ProfiledStagingError(
                "profiled staging transit recycle profile rejected"
            )

        profile = CML_REALIZATION_PROFILE_CATALOG[device.cml_realization_profile_id]

        node = self._node(lab_id, node_id)
        image = node.get("image_definition") or node.get("image_definition_id")

        if (
            node.get("label") != "transit-ios-01"
            or node.get("node_definition") != profile.node_definition
            or image != profile.image_definition
        ):
            raise ProfiledStagingError(
                "profiled staging transit recycle identity rejected"
            )

        state = node.get("state")

        if state != required_state:
            raise ProfiledStagingError(
                "profiled staging transit recycle state rejected"
            )

        return required_state

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
                    "profiled staging transit recycle completion is ambiguous"
                ) from None

            if state == expected:
                return expected

            if time.monotonic() >= deadline:
                raise ProfiledStagingAmbiguousError(
                    "profiled staging transit recycle completion is ambiguous"
                )

            time.sleep(self._POLL_SECONDS)

    def recycle(
        self,
        *,
        run_id: str,
        observed: ObservedStagingRealization,
        devices: tuple[ProfiledInventoryDevice, ...],
    ) -> EvidenceReference:
        """Recycle only the admitted IOSv transit node exactly once."""

        by_name = {str(device.logical_name): device for device in devices}

        if tuple(by_name) != PROFILED_STAGING_DEVICE_NAMES:
            raise ProfiledStagingError(
                "profiled staging transit recycle population rejected"
            )

        if observed.lab_title != f"NCDP Staging {run_id}":
            raise ProfiledStagingError(
                "profiled staging transit recycle realization rejected"
            )

        node_id = observed.node_ids.get("transit_ios_01")

        if not isinstance(node_id, str) or not node_id:
            raise ProfiledStagingError("profiled staging transit recycle node rejected")

        transit = by_name["transit-ios-01"]

        # First START must have fully booted the exact admitted IOSv.
        self._admit_exact_transit(
            run_id=run_id,
            lab_id=observed.lab_id,
            node_id=node_id,
            device=transit,
            required_state="BOOTED",
        )

        # Real IOSv diagnosis established that CML Day-0 reaches
        # persistent startup configuration after first boot while
        # legacy AutoInstall/DHCP can still own the running interface.
        # Give that first boot one bounded persistence interval before
        # recycling only this already-admitted disposable node.
        time.sleep(self._FIRST_BOOT_PERSISTENCE_SECONDS)

        self._admit_exact_transit(
            run_id=run_id,
            lab_id=observed.lab_id,
            node_id=node_id,
            device=transit,
            required_state="BOOTED",
        )

        # Exactly one STOP request. No blind retry.
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

        self._admit_exact_transit(
            run_id=run_id,
            lab_id=observed.lab_id,
            node_id=node_id,
            device=transit,
            required_state="STOPPED",
        )

        # Exactly one START request. No blind retry.
        self._put_state_once(
            lab_id=observed.lab_id,
            node_id=node_id,
            action="start",
            reconciled_states=frozenset(
                {
                    "QUEUED",
                    "STARTED",
                    "STARTING",
                    "BOOTING",
                    "BOOTED",
                }
            ),
        )

        booted = self._wait_for_state(
            lab_id=observed.lab_id,
            node_id=node_id,
            expected="BOOTED",
            timeout_seconds=self._START_TIMEOUT_SECONDS,
        )

        self._admit_exact_transit(
            run_id=run_id,
            lab_id=observed.lab_id,
            node_id=node_id,
            device=transit,
            required_state="BOOTED",
        )

        facts = {
            "run_id": run_id,
            "lab_id": observed.lab_id,
            "node_id": node_id,
            "device_identity": transit.device_identity,
            "logical_name": str(transit.logical_name),
            "cml_realization_profile_id": (transit.cml_realization_profile_id),
            "first_boot_persistence_seconds": (self._FIRST_BOOT_PERSISTENCE_SECONDS),
            "stop_state": stopped,
            "start_state": booted,
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
            identity=(f"staging-transit-recycle:{run_id}:transit-ios-01"),
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
) -> None:
    """Reject an existing staging lab or active fixed management endpoint."""
    for lab_id in reader.lab_ids():
        lab = reader.lab(lab_id)
        title = (lab or {}).get("lab_title") or (lab or {}).get("title")
        if isinstance(title, str) and title.startswith(STAGING_TITLE_PREFIX):
            raise ProfiledStagingError("existing NCDP Staging lab rejected")
    for device in devices:
        endpoint = device.management_endpoints.staging.binding.l3_endpoint
        if str(endpoint.address.ip) != STAGING_MANAGEMENT_ADDRESSES.get(
            str(device.logical_name)
        ):
            raise ProfiledStagingError("profiled staging management endpoint rejected")
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


_LINK_SLOTS = {
    "system_bridge_management": (("system_bridge", 0), ("management_switch", 0)),
    "management_core": (("management_switch", 1), ("core_02", 0)),
    "management_junos": (("management_switch", 2), ("edge_junos_01", 0)),
    "management_transit": (("management_switch", 3), ("transit_ios_01", 0)),
    "management_access": (("management_switch", 4), ("access_sw_01", 0)),
    "core_junos": (("core_02", 3), ("edge_junos_01", 1)),
    "core_transit": (("core_02", 1), ("transit_ios_01", 1)),
    "junos_transit": (("edge_junos_01", 2), ("transit_ios_01", 2)),
    "core_access": (("core_02", 2), ("access_sw_01", 1)),
}


def admit_created_realization(
    reader: ProfiledStagingCmlReader,
    run_id: str,
    outputs: dict[str, object],
    devices: tuple[ProfiledInventoryDevice, ...],
) -> ObservedStagingRealization:
    """Independently bind Terraform outputs to actual CML GET observations."""
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
        "core_02",
        "edge_junos_01",
        "transit_ios_01",
        "access_sw_01",
    }
    if set(node_ids) != expected_node_keys or set(link_ids) != set(_LINK_SLOTS):
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
    if len(actual_nodes) != PROFILED_STAGING_NODE_COUNT or actual_nodes != set(
        node_ids.values()
    ):
        raise ProfiledStagingError("profiled staging observed node population rejected")
    if len(actual_links) != PROFILED_STAGING_LINK_COUNT or actual_links != set(
        link_ids.values()
    ):
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
        profile = CML_REALIZATION_PROFILE_CATALOG[device.cml_realization_profile_id]
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
        management_marker = {
            "core-02": "interface GigabitEthernet1",
            "edge-junos-01": "fxp0",
            "transit-ios-01": "interface GigabitEthernet0/0",
            "access-sw-01": "interface GigabitEthernet0/0",
        }[str(device.logical_name)]
        if (
            str(device.expected_hostname) not in configuration
            or str(endpoint.address.ip) not in configuration
            or management_marker not in configuration
            or (
                str(device.logical_name) == "access-sw-01"
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
                device.cml_realization_profile_id
            ].physical_interface_slots
        }
        if catalog_slots != set(range(4)) or not catalog_slots.issubset(slots[key]):
            raise ProfiledStagingError(
                "profiled staging observed device slots rejected"
            )
    observed_links: dict[str, tuple[str, str]] = {}
    for key, ((left_node, left_slot), (right_node, right_slot)) in _LINK_SLOTS.items():
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
                "cml_profile": device.cml_realization_profile_id,
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
    topology = EvidenceReference(identity=f"staging-topology:{run_id}", digest=digest)
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
        topology_evidence=topology,
        cml_anchors=anchors,
    )
