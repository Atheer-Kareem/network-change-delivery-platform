#!/usr/bin/env python3
"""Enroll one exact fresh CML realization into private Oxidized SSH trust."""

from __future__ import annotations

import argparse
import os
import socket
import ssl
import sys

import httpx
import paramiko

from network_change_delivery.oxidized_host_trust import (
    DEFAULT_TRUST_ROOT,
    SUPPORTED_KEY_ALGORITHMS,
    HostTrustNode,
    OxidizedHostTrustError,
    parse_known_hosts,
    publish_host_trust,
)
from network_change_delivery.profiled_live_cml import (
    ACCESS_NODE_ID,
    CORE_NODE_ID,
    JUNOS_NODE_ID,
    LIVE_LAB_ID,
    TRANSIT_NODE_ID,
    ProfiledLiveCmlOperator,
)

LIVE_LAB = LIVE_LAB_ID
EXPECTED_CML_NODE_IDS = {
    "netbox-device-1": CORE_NODE_ID,
    "netbox-device-2": JUNOS_NODE_ID,
    "netbox-device-8": TRANSIT_NODE_ID,
    "netbox-device-9": ACCESS_NODE_ID,
}


class EnrollmentError(ValueError):
    """Bounded enrollment failure without CML configuration or key bytes."""


def _client() -> httpx.Client:
    address = os.environ.get("CML2_ADDRESS")
    certificate = os.environ.get("CML2_CACERT")
    if not address or not certificate:
        raise EnrollmentError("CML enrollment identity unavailable")
    context = ssl.create_default_context(cadata=certificate)
    client = httpx.Client(
        base_url=address.rstrip("/"), verify=context, timeout=20, trust_env=False
    )
    token = os.environ.get("CML2_TOKEN")
    if token:
        client.headers["Authorization"] = f"Bearer {token}"
    else:
        username = os.environ.get("NCDP_CML_STAGING_USERNAME")
        password = os.environ.get("NCDP_CML_STAGING_PASSWORD")
        if not username or not password:
            raise EnrollmentError("CML enrollment identity unavailable")
        try:
            response = client.post(
                "/api/v0/authenticate",
                json={"username": username, "password": password},
            )
            response.raise_for_status()
            payload = response.json()
            refreshed = payload if isinstance(payload, str) else payload.get("token")
        except (httpx.HTTPError, ValueError):
            raise EnrollmentError("CML enrollment authentication failed") from None
        if not isinstance(refreshed, str) or not refreshed:
            raise EnrollmentError("CML enrollment authentication failed")
        client.headers["Authorization"] = f"Bearer {refreshed}"
    return client


def _anchor(client: httpx.Client, lab_id: str, node_ids: dict[str, str]):
    if lab_id != LIVE_LAB:
        raise EnrollmentError("CML enrollment lab identity rejected")
    if node_ids != EXPECTED_CML_NODE_IDS:
        raise EnrollmentError("CML enrollment node identities rejected")
    try:
        return ProfiledLiveCmlOperator(client).anchor_profiled_live(
            transit_node_id=node_ids["netbox-device-8"],
            access_node_id=node_ids["netbox-device-9"],
        )
    except (KeyError, ValueError, RuntimeError):
        raise EnrollmentError("CML enrollment anchor rejected") from None


def _observe_key(address: str) -> str:
    """Observe one SSH/22 server key after its CML anchor is admitted."""
    connection: socket.socket | None = None
    transport: paramiko.Transport | None = None
    try:
        connection = socket.create_connection((address, 22), timeout=10)
        transport = paramiko.Transport(connection)
        transport.start_client(timeout=15)
        key = transport.get_remote_server_key()
        algorithm = key.get_name()
        encoded = key.get_base64()
        if algorithm not in SUPPORTED_KEY_ALGORITHMS or not encoded:
            raise EnrollmentError(f"SSH host-key algorithm rejected: {algorithm}")
        return f"{address} {algorithm} {encoded}"
    except (OSError, paramiko.SSHException):
        raise EnrollmentError("SSH host-key observation failed") from None
    finally:
        if transport is not None:
            transport.close()
        elif connection is not None:
            connection.close()


def enroll(lab_id: str, node_ids: dict[str, str]) -> None:
    client = _client()
    try:
        anchors = _anchor(client, lab_id, node_ids)
    finally:
        client.close()
    selected = {
        anchor.logical_name: _observe_key(anchor.management_address)
        for anchor in anchors
    }
    known_hosts = ("\n".join(selected.values()) + "\n").encode()
    parsed = parse_known_hosts(known_hosts)
    nodes = tuple(
        HostTrustNode(
            node=f"netbox-device-{anchor.device_id}",
            stable_name=anchor.logical_name,
            cml_node_id=anchor.cml_node_id,
            management_ip=anchor.management_address,
            algorithm=parsed[anchor.management_address][0],
            fingerprint=parsed[anchor.management_address][1],
        )
        for anchor in anchors
    )
    publish_host_trust(known_hosts, lab_id=lab_id, nodes=nodes, root=DEFAULT_TRUST_ROOT)
    for item in nodes:
        print(
            f"{item.node} {item.stable_name} {item.cml_node_id} "
            f"{item.management_ip} {item.algorithm} {item.fingerprint}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab-id", required=True)
    parser.add_argument("--core-id", default=CORE_NODE_ID)
    parser.add_argument("--junos-id", default=JUNOS_NODE_ID)
    parser.add_argument("--transit-id", default=TRANSIT_NODE_ID)
    parser.add_argument("--access-id", default=ACCESS_NODE_ID)
    arguments = parser.parse_args()
    try:
        enroll(
            arguments.lab_id,
            {
                "netbox-device-1": arguments.core_id,
                "netbox-device-2": arguments.junos_id,
                "netbox-device-8": arguments.transit_id,
                "netbox-device-9": arguments.access_id,
            },
        )
    except (EnrollmentError, OxidizedHostTrustError) as error:
        print(f"Oxidized CML host-trust enrollment failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
