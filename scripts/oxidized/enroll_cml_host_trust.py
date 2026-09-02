#!/usr/bin/env python3
"""Enroll one exact fresh CML realization into private Oxidized SSH trust."""

from __future__ import annotations

import argparse
import os
import ssl
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

from network_change_delivery.oxidized_host_trust import (
    DEFAULT_TRUST_ROOT,
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

SSH_KEYSCAN = Path("/usr/bin/ssh-keyscan")
SSH_KEYGEN = Path("/usr/bin/ssh-keygen")
LIVE_LAB = LIVE_LAB_ID
LIVE_TITLE = "NCDP Live"
ALGORITHM_PRIORITY = (
    "ssh-ed25519",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "ssh-rsa",
)


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


def _get(client: httpx.Client, path: str) -> Any:
    try:
        response = client.get(path)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        raise EnrollmentError("CML enrollment anchor unavailable") from None


def _configuration(client: httpx.Client, lab_id: str, node_id: str) -> str:
    for suffix in ("configuration", "configurations"):
        try:
            response = client.get(f"/api/v0/labs/{lab_id}/nodes/{node_id}/{suffix}")
            if response.status_code != 200:
                continue
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            continue
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict):
            value = payload.get("configuration") or payload.get("config/juniper.conf")
            if isinstance(value, str):
                return value
    node = _get(client, f"/api/v0/labs/{lab_id}/nodes/{node_id}")
    value = node.get("configuration") if isinstance(node, dict) else None
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
    raise EnrollmentError("CML stored Day-0 material unavailable")


def _anchor(client: httpx.Client, lab_id: str, node_ids: dict[str, str]):
    if lab_id != LIVE_LAB:
        raise EnrollmentError("CML enrollment lab identity rejected")
    try:
        return ProfiledLiveCmlOperator(client).anchor_profiled_live(
            transit_node_id=node_ids["netbox-device-8"],
            access_node_id=node_ids["netbox-device-9"],
        )
    except (KeyError, ValueError, RuntimeError):
        raise EnrollmentError("CML enrollment anchor rejected") from None


def _scan(host: str) -> str:
    if not SSH_KEYSCAN.is_file() or not SSH_KEYGEN.is_file():
        raise EnrollmentError("fixed OpenSSH executables unavailable")
    try:
        result = subprocess.run(
            [
                str(SSH_KEYSCAN),
                "-T",
                "10",
                "-t",
                "ed25519,ecdsa,rsa",
                "-p",
                "22",
                host,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        raise EnrollmentError("SSH host-key observation failed") from None
    choices: dict[str, str] = {}
    try:
        lines = result.stdout.decode("ascii").splitlines()
    except UnicodeDecodeError:
        raise EnrollmentError("SSH host-key observation malformed") from None
    for line in lines:
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 3 or fields[0] != host:
            raise EnrollmentError("SSH host-key identity rejected")
        algorithm = fields[1]
        if algorithm not in ALGORITHM_PRIORITY or algorithm in choices:
            raise EnrollmentError("SSH host-key observation conflicting")
        choices[algorithm] = line
    for algorithm in ALGORITHM_PRIORITY:
        if algorithm in choices:
            return choices[algorithm]
    raise EnrollmentError("SSH host-key observation unavailable")


def enroll(lab_id: str, node_ids: dict[str, str]) -> None:
    client = _client()
    try:
        anchors = _anchor(client, lab_id, node_ids)
    finally:
        client.close()
    selected = {
        anchor.logical_name: _scan(anchor.management_address) for anchor in anchors
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
