"""Bounded operator reconciliation for the persistent four-device CML lab."""

from __future__ import annotations

import base64
import hashlib
import os
import re
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any

import httpx

from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    CmlRealizationProfileID,
)

LIVE_LAB_ID = "09605569-0468-4fc4-8684-beb5a1342b9c"
LIVE_LAB_TITLE = "NCDP Live"
EXTERNAL_CONNECTOR_ID = "9155d0a4-e72b-4ab9-9f62-8d485de3ace0"
MANAGEMENT_SWITCH_ID = "e4542ca6-6fa9-46c6-bc95-6b437a8f270a"
CORE_NODE_ID = "59fc118d-dfa3-4a45-a905-6a056b591550"
JUNOS_NODE_ID = "3ee87d9c-09b5-4ed2-a655-092bf89b1190"
TRANSIT_NODE_ID = "b6a5e482-a867-4b88-addc-02eb068afb84"
ACCESS_NODE_ID = "fee01570-a8c6-478c-9e29-ebb991335346"

_BASE_NODE_IDS = frozenset(
    {EXTERNAL_CONNECTOR_ID, MANAGEMENT_SWITCH_ID, CORE_NODE_ID, JUNOS_NODE_ID}
)
_BASE_LINK_IDS = frozenset(
    {
        "80587f5c-4e5f-4552-8496-2ab9110f53e3",
        "ec2cac84-32d2-4628-a2a0-d4766f231105",
        "dfa3c1fc-fc56-4935-9c26-71722de48bca",
        "8eee9cd3-56f5-4d99-a48e-4e4a35bc007a",
    }
)
_CISCO_BASE64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_STANDARD_BASE64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_CISCO_BASE64_TABLE = str.maketrans(_STANDARD_BASE64, _CISCO_BASE64)
_TYPE9_SCRYPT = re.compile(r"^\$9\$[A-Za-z0-9./]{14}\$[A-Za-z0-9./]{43}$")


class ProfiledLiveCmlError(RuntimeError):
    """Bounded CML reconciliation failure without configuration or credentials."""


@dataclass(frozen=True)
class ProfiledLiveNodeSpec:
    """One exact new persistent profiled node realization."""

    logical_name: str
    device_id: int
    accepted_node_id: str
    label: str
    node_definition: str
    image_definition: str
    management_address: str
    automation_profile_id: AutomationProfileID
    cml_realization_profile_id: CmlRealizationProfileID
    password_salt: str
    routed_management: bool


NEW_NODE_SPECS = (
    ProfiledLiveNodeSpec(
        logical_name="transit-ios-01",
        device_id=8,
        accepted_node_id=TRANSIT_NODE_ID,
        label="transit-ios-01",
        node_definition="iosv",
        image_definition="iosv-159-3-m12",
        management_address="192.168.4.16",
        automation_profile_id=AutomationProfileID.IOSV_159_3_M12,
        cml_realization_profile_id=CmlRealizationProfileID.IOSV_159_3_M12,
        password_salt="ncdpd08B34salt",
        routed_management=False,
    ),
    ProfiledLiveNodeSpec(
        logical_name="access-sw-01",
        device_id=9,
        accepted_node_id=ACCESS_NODE_ID,
        label="access-sw-01",
        node_definition="iosvl2",
        image_definition="iosvl2-2020",
        management_address="192.168.4.17",
        automation_profile_id=AutomationProfileID.IOSVL2_2020,
        cml_realization_profile_id=CmlRealizationProfileID.IOSVL2_2020,
        password_salt="ncdpd09B34salt",
        routed_management=True,
    ),
)


@dataclass(frozen=True)
class ProfiledLiveCmlResult:
    """Secret-free result of exact persistent realization reconciliation."""

    lab_id: str
    transit_node_id: str
    access_node_id: str
    rebootstrapped_node_ids: tuple[str, ...]
    created_link_ids: tuple[str, ...]
    all_link_ids: tuple[str, ...]


@dataclass(frozen=True)
class ProfiledLiveAnchor:
    """Secret-free CML-controlled identity facts admitted before key observation."""

    logical_name: str
    device_id: int
    cml_node_id: str
    cml_label: str
    node_definition: str
    image_definition: str
    management_address: str
    management_port: int
    automation_profile_id: AutomationProfileID
    cml_realization_profile_id: CmlRealizationProfileID


def ios_scrypt_password_hash(password: str, salt: str) -> str:
    """Derive a deterministic IOS type-9 verifier without exposing plaintext."""
    if (
        not password
        or len(password) > 127
        or not password.isascii()
        or any(char.isspace() for char in password)
        or any(char in '?"' for char in password)
    ):
        raise ProfiledLiveCmlError("IOS bootstrap password is invalid")
    if re.fullmatch(r"[A-Za-z0-9./]{14}", salt) is None:
        raise ProfiledLiveCmlError("IOS bootstrap salt is invalid")
    try:
        digest = hashlib.scrypt(
            password.encode(), salt=salt.encode(), n=16384, r=1, p=1, dklen=32
        )
    except (TypeError, ValueError):
        raise ProfiledLiveCmlError("IOS bootstrap verifier generation failed") from None
    encoded = base64.b64encode(digest).decode().translate(_CISCO_BASE64_TABLE)[:-1]
    verifier = f"$9${salt}${encoded}"
    if _TYPE9_SCRYPT.fullmatch(verifier) is None:
        raise ProfiledLiveCmlError("IOS bootstrap verifier generation failed")
    return verifier


def render_ios_bootstrap(
    spec: ProfiledLiveNodeSpec,
    *,
    username: str,
    password_hash: str,
) -> str:
    """Render minimal hashed-secret Day-0 configuration for an exact IOS profile."""
    if username != "netdevops" or _TYPE9_SCRYPT.fullmatch(password_hash) is None:
        raise ProfiledLiveCmlError("IOS bootstrap identity is invalid")
    interface_lines = ["interface GigabitEthernet0/0"]
    if spec.routed_management:
        interface_lines.append(" no switchport")
    interface_lines.extend(
        (
            f" ip address {spec.management_address} 255.255.255.0",
            " no shutdown",
        )
    )
    return "\n".join(
        (
            f"hostname {spec.logical_name}",
            "!",
            "ip domain name ncdp.local",
            "!",
            f"username {username} privilege 15 secret 9 {password_hash}",
            "!",
            *interface_lines,
            "!",
            "ip ssh version 2",
            "!",
            "crypto key generate rsa modulus 2048",
            "!",
            "line vty 0 4",
            " login local",
            " transport input ssh",
            "!",
            "end",
            "",
        )
    )


class ProfiledLiveCmlOperator:
    """Admit the two accepted IOS nodes and reconcile five incident links."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    @classmethod
    def from_environment(cls) -> ProfiledLiveCmlOperator:
        address = os.environ.get("CML2_ADDRESS")
        certificate = os.environ.get("CML2_CACERT")
        username = os.environ.get("NCDP_CML_STAGING_USERNAME")
        password = os.environ.get("NCDP_CML_STAGING_PASSWORD")
        if not all((address, certificate, username, password)):
            raise ProfiledLiveCmlError("CML operator identity unavailable")
        try:
            context = ssl.create_default_context(cadata=certificate)
            client = httpx.Client(
                base_url=address.rstrip("/"),
                verify=context,
                timeout=20,
                trust_env=False,
                follow_redirects=False,
            )
            response = client.post(
                "/api/v0/authenticate",
                json={"username": username, "password": password},
            )
            response.raise_for_status()
            payload = response.json()
            token = payload if isinstance(payload, str) else payload.get("token")
        except (AttributeError, httpx.HTTPError, TypeError, ValueError):
            raise ProfiledLiveCmlError("CML operator authentication failed") from None
        if not isinstance(token, str) or not token:
            raise ProfiledLiveCmlError("CML operator authentication failed")
        client.headers["Authorization"] = f"Bearer {token}"
        return cls(client)

    def close(self) -> None:
        self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> httpx.Response:
        try:
            response = self._client.request(method, path, json=json)
        except httpx.HTTPError:
            raise ProfiledLiveCmlError("CML operator request failed") from None
        if response.status_code not in expected:
            raise ProfiledLiveCmlError(
                f"CML operator request rejected with status {response.status_code}"
            )
        return response

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            raise ProfiledLiveCmlError("CML operator response was invalid") from None

    def _get(self, path: str) -> Any:
        return self._json(self._request("GET", path))

    def _node(self, node_id: str) -> dict[str, object]:
        value = self._get(f"/api/v0/labs/{LIVE_LAB_ID}/nodes/{node_id}")
        if not isinstance(value, dict):
            raise ProfiledLiveCmlError("CML node response was invalid")
        return value

    def _configuration(self, node_id: str) -> str:
        for suffix in ("configuration", "configurations"):
            response = self._request(
                "GET",
                f"/api/v0/labs/{LIVE_LAB_ID}/nodes/{node_id}/{suffix}",
                expected=(200, 404, 405),
            )
            if response.status_code != 200:
                continue
            payload = self._json(response)
            if isinstance(payload, str):
                return payload
            if isinstance(payload, dict):
                configuration = payload.get("configuration")
                if isinstance(configuration, str):
                    return configuration
        node = self._node(node_id)
        configuration = node.get("configuration")
        if isinstance(configuration, str):
            return configuration
        if isinstance(configuration, list):
            contents = [
                item.get("content")
                for item in configuration
                if isinstance(item, dict) and isinstance(item.get("content"), str)
            ]
            if len(contents) == 1:
                return contents[0]
        raise ProfiledLiveCmlError("CML stored bootstrap is unavailable")

    def _interfaces(self, node_id: str) -> dict[int, dict[str, object]]:
        identifiers = self._get(
            f"/api/v0/labs/{LIVE_LAB_ID}/nodes/{node_id}/interfaces"
        )
        if not isinstance(identifiers, list):
            raise ProfiledLiveCmlError("CML interface population was invalid")
        interfaces: dict[int, dict[str, object]] = {}
        for identifier in identifiers:
            if not isinstance(identifier, str):
                raise ProfiledLiveCmlError("CML interface identity was invalid")
            value = self._get(f"/api/v0/labs/{LIVE_LAB_ID}/interfaces/{identifier}")
            if not isinstance(value, dict):
                raise ProfiledLiveCmlError("CML interface response was invalid")
            slot = value.get("slot")
            if isinstance(slot, int):
                if slot in interfaces:
                    raise ProfiledLiveCmlError("CML interface slot was duplicated")
                interfaces[slot] = value
        return interfaces

    def _preflight_lab(
        self, *, allow_stopped: bool = False
    ) -> tuple[list[str], list[str]]:
        lab = self._get(f"/api/v0/labs/{LIVE_LAB_ID}")
        if not isinstance(lab, dict):
            raise ProfiledLiveCmlError("persistent CML lab response was invalid")
        lab_state = lab.get("state")
        admitted_states = {"STARTED", "STOPPED"} if allow_stopped else {"STARTED"}
        if (
            lab.get("lab_title") or lab.get("title")
        ) != LIVE_LAB_TITLE or lab_state not in admitted_states:
            raise ProfiledLiveCmlError("persistent CML lab identity/state rejected")
        node_ids = self._get(f"/api/v0/labs/{LIVE_LAB_ID}/nodes")
        link_ids = self._get(f"/api/v0/labs/{LIVE_LAB_ID}/links")
        if not isinstance(node_ids, list) or not all(
            isinstance(item, str) for item in node_ids
        ):
            raise ProfiledLiveCmlError("persistent CML node population rejected")
        if not isinstance(link_ids, list) or not all(
            isinstance(item, str) for item in link_ids
        ):
            raise ProfiledLiveCmlError("persistent CML link population rejected")
        if not _BASE_NODE_IDS.issubset(node_ids) or not _BASE_LINK_IDS.issubset(
            link_ids
        ):
            raise ProfiledLiveCmlError("persistent CML baseline identity rejected")
        for node_id, label, definition, image in (
            (EXTERNAL_CONNECTOR_ID, "ext-conn-0", "external_connector", None),
            (MANAGEMENT_SWITCH_ID, "unmanaged-switch-0", "unmanaged_switch", None),
            (CORE_NODE_ID, "cat8000v-0", "cat8000v", "cat8000v-17-18-02"),
            (
                JUNOS_NODE_ID,
                "vjunos-router-0",
                "vjunos-router",
                "vjunos-router-23-2r1-15",
            ),
        ):
            node = self._node(node_id)
            actual_image = node.get("image_definition") or node.get(
                "image_definition_id"
            )
            if (
                node.get("label") != label
                or node.get("node_definition") != definition
                or actual_image != image
                or node.get("state")
                != ("STOPPED" if lab_state == "STOPPED" else "BOOTED")
            ):
                raise ProfiledLiveCmlError("persistent CML baseline node rejected")
        return node_ids, link_ids

    def _admit_node(
        self,
        spec: ProfiledLiveNodeSpec,
        configuration: str,
        node_ids: list[str],
    ) -> tuple[str, bool]:
        matches = [
            node_id
            for node_id in node_ids
            if self._node(node_id).get("label") == spec.label
        ]
        if len(matches) > 1:
            raise ProfiledLiveCmlError("persistent CML profiled node is ambiguous")
        if matches:
            node_id = matches[0]
            if node_id != spec.accepted_node_id:
                raise ProfiledLiveCmlError(
                    "persistent CML profiled node identity conflicts"
                )
            node = self._node(node_id)
            actual_image = node.get("image_definition") or node.get(
                "image_definition_id"
            )
            stored = self._configuration(node_id)
            if (
                node.get("node_definition") != spec.node_definition
                or actual_image != spec.image_definition
                or f"hostname {spec.logical_name}" not in stored
                or f"ip address {spec.management_address} 255.255.255.0" not in stored
            ):
                raise ProfiledLiveCmlError("persistent CML profiled node conflicts")
            if configuration.strip() == stored.strip():
                return node_id, False
            superseded = f"platform console serial\n!\n{configuration}".strip()
            if stored.strip() != superseded:
                expected_identity = next(
                    (
                        line
                        for line in configuration.splitlines()
                        if line.startswith("username netdevops privilege 15 secret 9 ")
                    ),
                    "",
                )
                if (
                    expected_identity
                    and expected_identity in stored.splitlines()
                    and " privilege 15 secret 0 " not in stored
                    and (not spec.routed_management or " no switchport" in stored)
                ):
                    return node_id, False
                raise ProfiledLiveCmlError(
                    "persistent CML profiled bootstrap conflicts"
                )
            return node_id, True
        raise ProfiledLiveCmlError("persistent CML profiled node is missing")

    def _links(self) -> dict[frozenset[str], str]:
        identifiers = self._get(f"/api/v0/labs/{LIVE_LAB_ID}/links")
        if not isinstance(identifiers, list):
            raise ProfiledLiveCmlError("CML link population was invalid")
        links: dict[frozenset[str], str] = {}
        for identifier in identifiers:
            if not isinstance(identifier, str):
                raise ProfiledLiveCmlError("CML link identity was invalid")
            value = self._get(f"/api/v0/labs/{LIVE_LAB_ID}/links/{identifier}")
            if not isinstance(value, dict):
                raise ProfiledLiveCmlError("CML link response was invalid")
            endpoints = frozenset(
                (str(value.get("interface_a")), str(value.get("interface_b")))
            )
            if len(endpoints) != 2 or endpoints in links:
                raise ProfiledLiveCmlError("CML link endpoints were invalid")
            links[endpoints] = identifier
        return links

    def _ensure_link(
        self,
        interface_a: str,
        interface_b: str,
        links: dict[frozenset[str], str],
    ) -> tuple[str, bool]:
        endpoints = frozenset((interface_a, interface_b))
        if endpoints in links:
            return links[endpoints], False
        if any(interface_a in pair or interface_b in pair for pair in links):
            raise ProfiledLiveCmlError("CML desired link endpoint is already occupied")
        response = self._request(
            "POST",
            f"/api/v0/labs/{LIVE_LAB_ID}/links",
            json={"src_int": interface_a, "dst_int": interface_b},
            expected=(200, 201),
        )
        payload = self._json(response)
        link_id = payload if isinstance(payload, str) else payload.get("id")
        if not isinstance(link_id, str) or not link_id:
            raise ProfiledLiveCmlError("CML created link identity was invalid")
        links[endpoints] = link_id
        return link_id, True

    @staticmethod
    def _interface_id(interfaces: dict[int, dict[str, object]], slot: int) -> str:
        item = interfaces.get(slot)
        identifier = item.get("id") if item else None
        if not isinstance(identifier, str):
            raise ProfiledLiveCmlError("CML required interface slot is unavailable")
        return identifier

    def _start_and_wait(self, node_id: str, management_address: str) -> None:
        node = self._node(node_id)
        if node.get("state") in {"STOPPED", "DEFINED_ON_CORE"}:
            self._request(
                "PUT",
                f"/api/v0/labs/{LIVE_LAB_ID}/nodes/{node_id}/state/start",
                expected=(200, 204),
            )
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            if self._node(node_id).get("state") == "BOOTED":
                try:
                    with socket.create_connection((management_address, 22), timeout=3):
                        return
                except OSError:
                    pass
            time.sleep(5)
        raise ProfiledLiveCmlError("profiled LIVE node readiness timed out")

    def _rebootstrap_new_nodes(self, configurations: dict[str, str]) -> None:
        """Apply corrected Day-0 through CML's required whole-lab edit cycle."""
        if not configurations or _BASE_NODE_IDS.intersection(configurations):
            raise ProfiledLiveCmlError("baseline CML node rebootstrap rejected")
        lab = self._get(f"/api/v0/labs/{LIVE_LAB_ID}")
        if not isinstance(lab, dict) or lab.get("state") not in {"STARTED", "STOPPED"}:
            raise ProfiledLiveCmlError("profiled LIVE lab edit state rejected")
        if lab.get("state") == "STARTED":
            # This CML release can return 400 when one node is already stopped while
            # still completing the requested whole-lab stop.  Admission therefore
            # depends on the independently observed final state below.
            self._request(
                "PUT",
                f"/api/v0/labs/{LIVE_LAB_ID}/stop",
                expected=(200, 204, 400),
            )
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            lab = self._get(f"/api/v0/labs/{LIVE_LAB_ID}")
            if isinstance(lab, dict) and lab.get("state") == "STOPPED":
                break
            time.sleep(3)
        else:
            raise ProfiledLiveCmlError("profiled LIVE lab stop timed out")
        for node_id, configuration in configurations.items():
            self._request(
                "PUT",
                f"/api/v0/labs/{LIVE_LAB_ID}/nodes/{node_id}/wipe_disks",
                expected=(200, 204),
            )
            self._request(
                "PATCH",
                f"/api/v0/labs/{LIVE_LAB_ID}/nodes/{node_id}",
                json={
                    "configuration": [
                        {"name": "ios_config.txt", "content": configuration}
                    ]
                },
                expected=(200, 204),
            )
        self._request(
            "PUT",
            f"/api/v0/labs/{LIVE_LAB_ID}/start",
            expected=(200, 204),
        )

    def realize(
        self,
        *,
        usernames: dict[int, str],
        password_hashes: dict[int, str],
    ) -> ProfiledLiveCmlResult:
        """Reconcile exact new nodes/links and wait for bounded SSH readiness."""
        if set(usernames) != {8, 9} or set(password_hashes) != {8, 9}:
            raise ProfiledLiveCmlError("profiled LIVE bootstrap inputs rejected")
        node_ids, _ = self._preflight_lab(allow_stopped=True)
        configurations = {
            spec.device_id: render_ios_bootstrap(
                spec,
                username=usernames[spec.device_id],
                password_hash=password_hashes[spec.device_id],
            )
            for spec in NEW_NODE_SPECS
        }
        rebootstrapped_nodes: list[str] = []
        resolved: dict[str, str] = {}
        for spec in NEW_NODE_SPECS:
            node_id, rebootstrap = self._admit_node(
                spec, configurations[spec.device_id], node_ids
            )
            resolved[spec.logical_name] = node_id
            if rebootstrap:
                rebootstrapped_nodes.append(node_id)
        if set(node_ids) != _BASE_NODE_IDS | set(resolved.values()):
            raise ProfiledLiveCmlError("persistent CML node population has extras")

        interfaces = {
            "management": self._interfaces(MANAGEMENT_SWITCH_ID),
            "core-02": self._interfaces(CORE_NODE_ID),
            "edge-junos-01": self._interfaces(JUNOS_NODE_ID),
            "transit-ios-01": self._interfaces(resolved["transit-ios-01"]),
            "access-sw-01": self._interfaces(resolved["access-sw-01"]),
        }
        if set(interfaces["transit-ios-01"]) != {0, 1, 2, 3} or set(
            interfaces["access-sw-01"]
        ) != {0, 1, 2, 3}:
            raise ProfiledLiveCmlError("profiled IOS interface slots are not exact")
        desired_links = (
            ("management", 6, "transit-ios-01", 0),
            ("management", 7, "access-sw-01", 0),
            ("core-02", 1, "transit-ios-01", 1),
            ("edge-junos-01", 2, "transit-ios-01", 2),
            ("core-02", 2, "access-sw-01", 1),
        )
        links = self._links()
        created_links: list[str] = []
        for node_a, slot_a, node_b, slot_b in desired_links:
            link_id, created = self._ensure_link(
                self._interface_id(interfaces[node_a], slot_a),
                self._interface_id(interfaces[node_b], slot_b),
                links,
            )
            if created:
                created_links.append(link_id)
        if len(links) != 9:
            raise ProfiledLiveCmlError(
                "persistent CML final link population is not exact"
            )

        configuration_by_node = {
            resolved[spec.logical_name]: configurations[spec.device_id]
            for spec in NEW_NODE_SPECS
        }
        if rebootstrapped_nodes:
            self._rebootstrap_new_nodes(
                {
                    node_id: configuration_by_node[node_id]
                    for node_id in rebootstrapped_nodes
                }
            )
        for spec in NEW_NODE_SPECS:
            self._start_and_wait(resolved[spec.logical_name], spec.management_address)
        return ProfiledLiveCmlResult(
            lab_id=LIVE_LAB_ID,
            transit_node_id=resolved["transit-ios-01"],
            access_node_id=resolved["access-sw-01"],
            rebootstrapped_node_ids=tuple(rebootstrapped_nodes),
            created_link_ids=tuple(created_links),
            all_link_ids=tuple(sorted(links.values())),
        )

    def anchor_profiled_live(
        self,
        *,
        transit_node_id: str,
        access_node_id: str,
    ) -> tuple[ProfiledLiveAnchor, ...]:
        """Admit exact CML identity/configuration before network key observation."""
        if transit_node_id != TRANSIT_NODE_ID or access_node_id != ACCESS_NODE_ID:
            raise ProfiledLiveCmlError("profiled LIVE CML node identity rejected")
        node_ids, link_ids = self._preflight_lab()
        expected_ids = _BASE_NODE_IDS | {transit_node_id, access_node_id}
        if set(node_ids) != expected_ids or len(link_ids) != 9:
            raise ProfiledLiveCmlError("persistent CML profiled population rejected")
        specifications = (
            (
                "core-02",
                1,
                CORE_NODE_ID,
                "cat8000v-0",
                "cat8000v",
                "cat8000v-17-18-02",
                "192.168.4.14",
                22,
                AutomationProfileID.CAT8000V_IOSXE,
                CmlRealizationProfileID.CAT8000V_17_18_02,
            ),
            (
                "edge-junos-01",
                2,
                JUNOS_NODE_ID,
                "vjunos-router-0",
                "vjunos-router",
                "vjunos-router-23-2r1-15",
                "192.168.4.20",
                830,
                AutomationProfileID.VJUNOS_ROUTER,
                CmlRealizationProfileID.VJUNOS_ROUTER_23_2R1_15,
            ),
            (
                "transit-ios-01",
                8,
                transit_node_id,
                "transit-ios-01",
                "iosv",
                "iosv-159-3-m12",
                "192.168.4.16",
                22,
                AutomationProfileID.IOSV_159_3_M12,
                CmlRealizationProfileID.IOSV_159_3_M12,
            ),
            (
                "access-sw-01",
                9,
                access_node_id,
                "access-sw-01",
                "iosvl2",
                "iosvl2-2020",
                "192.168.4.17",
                22,
                AutomationProfileID.IOSVL2_2020,
                CmlRealizationProfileID.IOSVL2_2020,
            ),
        )
        anchors: list[ProfiledLiveAnchor] = []
        for (
            logical_name,
            device_id,
            node_id,
            label,
            definition,
            image,
            address,
            port,
            automation_profile,
            realization_profile,
        ) in specifications:
            node = self._node(node_id)
            configuration = self._configuration(node_id)
            actual_image = node.get("image_definition") or node.get(
                "image_definition_id"
            )
            if (
                node.get("label") != label
                or node.get("node_definition") != definition
                or actual_image != image
                or node.get("state") != "BOOTED"
                or logical_name not in configuration
                or address not in configuration
            ):
                raise ProfiledLiveCmlError("profiled LIVE CML anchor rejected")
            if device_id in {8, 9} and (
                " privilege 15 secret 9 $9$" not in configuration
                or " privilege 15 secret 0 " in configuration
            ):
                raise ProfiledLiveCmlError("profiled LIVE hashed bootstrap rejected")
            if device_id == 9 and " no switchport" not in configuration:
                raise ProfiledLiveCmlError(
                    "profiled LIVE routed management anchor rejected"
                )
            anchors.append(
                ProfiledLiveAnchor(
                    logical_name=logical_name,
                    device_id=device_id,
                    cml_node_id=node_id,
                    cml_label=label,
                    node_definition=definition,
                    image_definition=image,
                    management_address=address,
                    management_port=port,
                    automation_profile_id=automation_profile,
                    cml_realization_profile_id=realization_profile,
                )
            )
        return tuple(anchors)
