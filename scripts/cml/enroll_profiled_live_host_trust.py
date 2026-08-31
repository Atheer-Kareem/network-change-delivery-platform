#!/usr/bin/env python3
"""Enroll exact-four CML-anchored profiled LIVE SSH host trust."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import socket
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import paramiko

from network_change_delivery.profiled_live_cml import (
    LIVE_LAB_ID,
    LIVE_LAB_TITLE,
    ProfiledLiveAnchor,
    ProfiledLiveCmlError,
    ProfiledLiveCmlOperator,
)
from network_change_delivery.profiled_live_host_trust import (
    ProfiledLiveHostTrustError,
    publish_profiled_live_host_trust,
)
from network_change_delivery.profiled_realization import (
    CmlAnchoredHostTrustGeneration,
    CmlAnchoredHostTrustRecord,
    EvidenceReference,
    RealizationEnvironment,
    SSHHostKeyType,
)


class EnrollmentError(ValueError):
    """Bounded enrollment failure without key or configuration bytes."""


def _observe_key(anchor: ProfiledLiveAnchor) -> tuple[str, str, str]:
    """Observe key material only after caller establishes the CML anchor."""
    transport: paramiko.Transport | None = None
    connection: socket.socket | None = None
    try:
        connection = socket.create_connection(
            (anchor.management_address, anchor.management_port), timeout=10
        )
        transport = paramiko.Transport(connection)
        transport.start_client(timeout=15)
        key = transport.get_remote_server_key()
        algorithm = key.get_name()
        encoded = key.get_base64()
        digest = hashlib.sha256(key.asbytes()).digest()
    except (OSError, paramiko.SSHException):
        raise EnrollmentError("profiled LIVE SSH key observation failed") from None
    finally:
        if transport is not None:
            transport.close()
        elif connection is not None:
            connection.close()
    if algorithm not in {item.value for item in SSHHostKeyType} or not encoded:
        raise EnrollmentError("profiled LIVE SSH key algorithm rejected")
    fingerprint = "SHA256:" + base64.b64encode(digest).decode().rstrip("=")
    return algorithm, encoded, fingerprint


def _anchor_evidence(anchor: ProfiledLiveAnchor) -> EvidenceReference:
    value = {
        **asdict(anchor),
        "automation_profile_id": anchor.automation_profile_id.value,
        "cml_realization_profile_id": anchor.cml_realization_profile_id.value,
        "lab_id": LIVE_LAB_ID,
        "lab_title": LIVE_LAB_TITLE,
        "booted": True,
        "hostname_marker": True,
        "management_address_marker": True,
    }
    digest = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return EvidenceReference(
        identity=f"cml-anchor:netbox-device-{anchor.device_id}",
        digest=f"sha256:{digest}",
    )


def enroll(transit_node_id: str, access_node_id: str) -> CmlAnchoredHostTrustGeneration:
    operator = ProfiledLiveCmlOperator.from_environment()
    try:
        anchors = operator.anchor_profiled_live(
            transit_node_id=transit_node_id,
            access_node_id=access_node_id,
        )
    finally:
        operator.close()
    observations = tuple((anchor, _observe_key(anchor)) for anchor in anchors)
    known_hosts = "".join(
        f"{anchor.management_address} {algorithm} {encoded}\n"
        for anchor, (algorithm, encoded, _fingerprint) in observations
    ).encode("ascii")
    generation_reference = EvidenceReference(
        identity="profiled-live-trust:known-hosts",
        digest=f"sha256:{hashlib.sha256(known_hosts).hexdigest()}",
    )
    now = datetime.now(UTC)
    records = tuple(
        CmlAnchoredHostTrustRecord(
            environment=RealizationEnvironment.LIVE,
            realization_identity="ncdp-live",
            cml_lab_id=LIVE_LAB_ID,
            cml_node_id=anchor.cml_node_id,
            device_identity=f"netbox:dcim.device:{anchor.device_id}",
            logical_name=anchor.logical_name,
            management_address=anchor.management_address,
            management_port=anchor.management_port,
            automation_profile_id=anchor.automation_profile_id,
            cml_realization_profile_id=anchor.cml_realization_profile_id,
            host_key_type=SSHHostKeyType(algorithm),
            host_key_fingerprint=fingerprint,
            cml_anchor_evidence=_anchor_evidence(anchor),
            admitted_at=now,
            trust_generation=generation_reference,
        )
        for anchor, (algorithm, _encoded, fingerprint) in observations
    )
    generation = CmlAnchoredHostTrustGeneration(
        environment=RealizationEnvironment.LIVE,
        realization_identity="ncdp-live",
        cml_lab_id=LIVE_LAB_ID,
        admitted_at=now,
        expires_at=now + timedelta(days=365),
        generation_evidence=generation_reference,
        records=records,
    )
    return publish_profiled_live_host_trust(known_hosts, generation)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transit-node-id", required=True)
    parser.add_argument("--access-node-id", required=True)
    arguments = parser.parse_args()
    try:
        generation = enroll(arguments.transit_node_id, arguments.access_node_id)
    except (
        EnrollmentError,
        ProfiledLiveCmlError,
        ProfiledLiveHostTrustError,
        ValueError,
    ) as error:
        print(f"profiled LIVE host-trust enrollment failed: {error}", file=sys.stderr)
        return 2
    for record in generation.records:
        print(
            f"{record.logical_name} {record.host_key_type.value} "
            f"{record.host_key_fingerprint} CML-ANCHOR-PASS"
        )
    print(f"profiled LIVE trust digest: {generation.generation_evidence.digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
