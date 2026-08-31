"""Persistent exact-four profiled LIVE host-trust tests."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from network_change_delivery.profile_inventory import PROFILED_POPULATION_CATALOG
from network_change_delivery.profiled_live_host_trust import (
    AMBIGUITY_NAME,
    EXPECTED_LIVE_ADDRESSES,
    EXPECTED_LIVE_ENDPOINTS,
    EXPECTED_LIVE_NODE_IDS,
    KNOWN_HOSTS_NAME,
    METADATA_NAME,
    ProfiledLiveHostTrustError,
    parse_profiled_live_known_hosts,
    publish_profiled_live_host_trust,
    validate_profiled_live_host_trust,
)
from network_change_delivery.profiled_realization import (
    CmlAnchoredHostTrustGeneration,
    CmlAnchoredHostTrustRecord,
    EvidenceReference,
    RealizationEnvironment,
    SSHHostKeyType,
)

LAB_ID = "09605569-0468-4fc4-8684-beb5a1342b9c"
NODE_IDS = EXPECTED_LIVE_NODE_IDS


def key(seed: str) -> tuple[str, str]:
    value = seed.encode()
    encoded = base64.b64encode(value).decode()
    fingerprint = base64.b64encode(hashlib.sha256(value).digest()).decode().rstrip("=")
    return encoded, f"SHA256:{fingerprint}"


def material() -> tuple[bytes, CmlAnchoredHostTrustGeneration]:
    observations = tuple(key(f"profiled-live-key-{index}") for index in range(4))
    known_hosts = "".join(
        f"{address} ssh-rsa {observations[index][0]}\n"
        for index, address in enumerate(EXPECTED_LIVE_ADDRESSES)
    ).encode()
    generation_evidence = EvidenceReference(
        identity="profiled-live-trust:known-hosts",
        digest=f"sha256:{hashlib.sha256(known_hosts).hexdigest()}",
    )
    now = datetime(2026, 8, 31, tzinfo=UTC)
    records = tuple(
        CmlAnchoredHostTrustRecord(
            environment=RealizationEnvironment.LIVE,
            realization_identity="ncdp-live",
            cml_lab_id=LAB_ID,
            cml_node_id=NODE_IDS[index],
            device_identity=f"netbox:dcim.device:{device_id}",
            logical_name=member.logical_name,
            management_address=EXPECTED_LIVE_ADDRESSES[index],
            management_port=EXPECTED_LIVE_ENDPOINTS[index][1],
            automation_profile_id=member.automation_profile_id,
            cml_realization_profile_id=member.cml_realization_profile_id,
            host_key_type=SSHHostKeyType.SSH_RSA,
            host_key_fingerprint=observations[index][1],
            cml_anchor_evidence=EvidenceReference(
                identity=f"cml-anchor:netbox-device-{device_id}",
                digest=f"sha256:{str(index + 1) * 64}",
            ),
            admitted_at=now,
            trust_generation=generation_evidence,
        )
        for index, (member, device_id) in enumerate(
            zip(PROFILED_POPULATION_CATALOG, (1, 2, 8, 9), strict=True)
        )
    )
    generation = CmlAnchoredHostTrustGeneration(
        environment=RealizationEnvironment.LIVE,
        realization_identity="ncdp-live",
        cml_lab_id=LAB_ID,
        admitted_at=now,
        expires_at=now + timedelta(days=365),
        generation_evidence=generation_evidence,
        records=records,
    )
    return known_hosts, generation


def test_exact_four_profiled_live_generation_publishes_atomically(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private" / "profiled-live"
    known_hosts, generation = material()
    assert publish_profiled_live_host_trust(known_hosts, generation, root) == generation
    assert validate_profiled_live_host_trust(root) == generation
    assert (root / KNOWN_HOSTS_NAME).stat().st_mode & 0o777 == 0o600
    assert (root / METADATA_NAME).stat().st_mode & 0o777 == 0o600
    assert not (root / AMBIGUITY_NAME).exists()
    metadata = (root / METADATA_NAME).read_text()
    for forbidden in ("public_key", "raw_public_key", observations_key(known_hosts)):
        assert forbidden not in metadata


def observations_key(known_hosts: bytes) -> str:
    return known_hosts.decode().split()[2]


@pytest.mark.parametrize(
    "mutator",
    (
        lambda lines: lines[:-1],
        lambda lines: [lines[1], lines[0], *lines[2:]],
        lambda lines: [*lines, lines[-1]],
        lambda lines: [lines[0].replace("192.168.4.14", "192.168.4.99"), *lines[1:]],
    ),
)
def test_missing_reordered_duplicate_or_unknown_host_fails_closed(mutator) -> None:
    known_hosts, _ = material()
    lines = known_hosts.decode().splitlines()
    candidate = ("\n".join(mutator(lines)) + "\n").encode()
    with pytest.raises(ProfiledLiveHostTrustError):
        parse_profiled_live_known_hosts(candidate)


def test_digest_or_record_mismatch_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "private" / "profiled-live"
    known_hosts, generation = material()
    wrong_digest = generation.model_copy(
        update={
            "generation_evidence": generation.generation_evidence.model_copy(
                update={"digest": f"sha256:{'f' * 64}"}
            )
        }
    )
    with pytest.raises(ProfiledLiveHostTrustError, match="digest"):
        publish_profiled_live_host_trust(known_hosts, wrong_digest, root)

    records = list(generation.records)
    records[0] = records[0].model_copy(update={"management_address": "192.168.4.16"})
    bad_record = generation.model_copy(update={"records": tuple(records)})
    with pytest.raises(ProfiledLiveHostTrustError, match="record"):
        publish_profiled_live_host_trust(known_hosts, bad_record, root)

    wrong_lab = generation.model_copy(
        update={"cml_lab_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}
    )
    with pytest.raises(ProfiledLiveHostTrustError, match="population"):
        publish_profiled_live_host_trust(known_hosts, wrong_lab, root)


def test_profiled_trust_is_not_the_oxidized_exact_two_authority() -> None:
    from network_change_delivery.oxidized_host_trust import DEFAULT_TRUST_ROOT
    from network_change_delivery.profiled_live_host_trust import (
        DEFAULT_PROFILED_LIVE_TRUST_ROOT,
    )

    assert DEFAULT_PROFILED_LIVE_TRUST_ROOT != DEFAULT_TRUST_ROOT
    assert "oxidized" not in DEFAULT_PROFILED_LIVE_TRUST_ROOT.parts
