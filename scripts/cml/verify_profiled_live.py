#!/usr/bin/env python3
"""Verify exact-four profiled LIVE inventory, trust, and read-only collection."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime

from network_change_delivery.ansible_adapter import ProviderError
from network_change_delivery.inventory import NetBoxInventoryProvider
from network_change_delivery.profile_inventory import NetBoxProfileInventoryProvider
from network_change_delivery.profile_read_only_adapter import ProfileReadOnlyAdapter
from network_change_delivery.profiled_live_cml import (
    LIVE_LAB_ID,
    LIVE_LAB_TITLE,
    ProfiledLiveCmlError,
    ProfiledLiveCmlOperator,
)
from network_change_delivery.profiled_live_host_trust import (
    DEFAULT_PROFILED_LIVE_TRUST_ROOT,
    KNOWN_HOSTS_NAME,
    ProfiledLiveHostTrustError,
    validate_profiled_live_host_trust,
)
from network_change_delivery.profiled_realization import (
    EvidenceReference,
    PersistentProfiledRealization,
    ProfiledRealizedDevice,
    RealizationLifecycleState,
)
from network_change_delivery.secrets import OpenBaoSecretProvider, SecretError


class VerificationError(RuntimeError):
    """Bounded LIVE verification failure without provider or secret payloads."""


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def verify(transit_node_id: str, access_node_id: str) -> PersistentProfiledRealization:
    trust = validate_profiled_live_host_trust()
    operator = ProfiledLiveCmlOperator.from_environment()
    try:
        anchors = operator.anchor_profiled_live(
            transit_node_id=transit_node_id,
            access_node_id=access_node_id,
        )
    finally:
        operator.close()
    profiled = NetBoxProfileInventoryProvider().resolve_profiled_population()
    legacy = NetBoxInventoryProvider().resolve_managed_devices()
    if tuple(device.name for device in legacy) != ("core-02", "edge-junos-01"):
        raise VerificationError("legacy managed population is not exact-two")
    anchors_by_name = {anchor.logical_name: anchor for anchor in anchors}
    trust_by_name = {str(record.logical_name): record for record in trust.records}
    if len(anchors_by_name) != 4 or len(trust_by_name) != 4:
        raise VerificationError("profiled LIVE evidence population is not exact")

    realized = tuple(
        ProfiledRealizedDevice(
            device_identity=device.device_identity,
            logical_name=device.logical_name,
            operational_role=device.operational_role,
            automation_profile_id=device.automation_profile_id,
            cml_realization_profile_id=device.cml_realization_profile_id,
            cml_node_id=anchors_by_name[device.logical_name].cml_node_id,
            lifecycle_state=RealizationLifecycleState.READY,
            readiness_evidence=EvidenceReference(
                identity=f"live-readiness:{device.logical_name}",
                digest=_digest(
                    {
                        "node": anchors_by_name[device.logical_name].cml_node_id,
                        "address": device.live_read_only_target().host,
                        "ready": True,
                    }
                ),
            ),
            management_endpoint=device.management_endpoints.live,
        )
        for device in profiled.devices
    )
    realization = PersistentProfiledRealization(
        realization_identity="ncdp-live",
        cml_lab_id=LIVE_LAB_ID,
        cml_lab_title=LIVE_LAB_TITLE,
        lifecycle_state=RealizationLifecycleState.READY,
        admitted_at=trust.admitted_at,
        expires_at=trust.expires_at,
        admission_evidence=trust.generation_evidence,
        devices=realized,
    )
    provider = OpenBaoSecretProvider()
    adapter = ProfileReadOnlyAdapter(
        known_hosts=DEFAULT_PROFILED_LIVE_TRUST_ROOT / KNOWN_HOSTS_NAME
    )
    for device in profiled.devices:
        target = device.live_read_only_target()
        record = trust_by_name[device.logical_name]
        anchor = anchors_by_name[device.logical_name]
        if (
            target.host != str(record.management_address)
            or target.port != record.management_port
            or device.device_identity != record.device_identity
            or record.cml_node_id != anchor.cml_node_id
            or record.automation_profile_id is not device.automation_profile_id
            or record.cml_realization_profile_id
            is not device.cml_realization_profile_id
        ):
            raise VerificationError("profiled LIVE target is detached from trust")
        credentials = provider.load(device)
        states = adapter.discover(target, credentials)
        if not states or {state.observed_hostname for state in states} != {
            device.expected_hostname
        }:
            raise VerificationError("profiled LIVE hostname verification failed")
        if device.logical_name in {"transit-ios-01", "access-sw-01"}:
            physical = {
                state.interface
                for state in states
                if state.interface.startswith("GigabitEthernet0/")
            }
            expected = {f"GigabitEthernet0/{slot}" for slot in range(4)}
            if physical != expected:
                raise VerificationError("profiled IOS interface population rejected")
        if device.logical_name == "access-sw-01":
            management = [
                state for state in states if state.interface == "GigabitEthernet0/0"
            ]
            if len(management) != 1 or "192.168.4.17/24" not in set(
                management[0].ipv4_addresses
            ):
                raise VerificationError("IOSvL2 routed management verification failed")
        version = next(
            (state.software_version for state in states if state.software_version), None
        )
        print(
            f"LIVE {device.logical_name} profile={device.automation_profile_id.value} "
            f"host={target.host} hostname={device.expected_hostname} "
            f"interfaces={len(states)} version={version or 'unreported'} PASS"
        )
    print("profiled population exact-four PASS")
    print("legacy population exact-two PASS")
    print(
        f"persistent realization digest: {_digest(realization.model_dump(mode='json'))}"
    )
    print(f"verified at: {datetime.now(UTC).isoformat()}")
    return realization


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "usage: verify_profiled_live.py TRANSIT_NODE_UUID ACCESS_NODE_UUID",
            file=sys.stderr,
        )
        return 2
    try:
        verify(sys.argv[1], sys.argv[2])
    except (
        ProfiledLiveCmlError,
        ProfiledLiveHostTrustError,
        ProviderError,
        SecretError,
        VerificationError,
        ValueError,
    ) as error:
        print(f"profiled LIVE verification failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
