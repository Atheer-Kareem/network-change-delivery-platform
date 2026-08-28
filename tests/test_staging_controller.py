from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from network_change_delivery.protected_staging import (
    BROWNFIELD_LAB_UUID,
    EXPECTED_TERRAFORM_ADDRESSES,
    ProtectedStagingError,
    ProtectedStagingSecretAuthority,
    ProtectedStagingTarget,
)
from network_change_delivery.secrets import SecretError
from network_change_delivery.staging_controller import (
    authority_from_environment,
    require_merged_main_context,
)


def buildkite_environment() -> dict[str, str]:
    return {
        "BUILDKITE_PIPELINE_ID": "f5c3ad42-8558-4276-8d26-6014a9cc0638",
        "BUILDKITE_BUILD_ID": "79c012df-23bf-49b3-a6dd-f28799c4bb24",
        "BUILDKITE_COMMIT": "a" * 40,
        "BUILDKITE_BRANCH": "main",
        "BUILDKITE_PULL_REQUEST": "false",
        "BUILDKITE_STEP_KEY": "cml-staging",
        "BUILDKITE_JOB_ID": "034e9347-3a01-44cb-8487-4701f9c33d07",
        "BUILDKITE_AGENT_META_DATA_QUEUE": "ncdp-staging",
        "BUILDKITE_RETRY_COUNT": "0",
    }


def authority_environment() -> dict[str, str]:
    return {
        "NCDP_NETBOX_URL": "https://netbox.example.test",
        "NCDP_OPENBAO_URL": "https://bao.example.test",
        "CML2_ADDRESS": "https://cml.example.test",
        "CML2_CACERT": "synthetic test CA",
    }


def test_only_merged_main_is_admitted() -> None:
    environment = buildkite_environment()
    context = require_merged_main_context(environment)
    assert context.branch == "main"

    for branch, pull_request in (("feature", "false"), ("main", "123")):
        rejected = environment | {
            "BUILDKITE_BRANCH": branch,
            "BUILDKITE_PULL_REQUEST": pull_request,
        }
        with pytest.raises(ProtectedStagingError, match="reviewed merged main"):
            require_merged_main_context(rejected)


def test_domain_authority_is_exactly_disposable_staging() -> None:
    context = require_merged_main_context(buildkite_environment())
    authority = authority_from_environment(context, authority_environment())
    assert {authority.cisco.device_id, authority.junos.device_id} == {6, 7}
    assert {authority.cisco.live_homolog_id, authority.junos.live_homolog_id} == {
        1,
        2,
    }
    assert {authority.cisco.management_ip, authority.junos.management_ip} == {
        "192.168.4.30",
        "192.168.4.31",
    }
    assert set(authority.live_deny_device_ids) == {1, 2, 3}
    assert set(authority.live_deny_management_ips) == {
        "192.168.4.14",
        "192.168.4.15",
        "192.168.4.20",
    }
    assert authority.cml.denied_lab_uuids == (BROWNFIELD_LAB_UUID,)
    assert set(authority.terraform_addresses) == EXPECTED_TERRAFORM_ADDRESSES
    assert len(authority.terraform_addresses) == 10


@pytest.mark.parametrize("device_id", [1, 2, 3, 8])
def test_staging_secret_authority_rejects_non_staging_ids(device_id: int) -> None:
    target = ProtectedStagingTarget.model_construct(
        device_id=device_id,
        name="not-staging",
        host="192.168.4.14",
        platform="cisco_iosxe",
        management_interface="GigabitEthernet1",
        interface_id=1,
        management_cidr="192.168.4.14/24",
        ip_address_id=1,
        live_homolog_id=1,
        credential_reference=f"openbao:kv-v2:ncdp/devices/{device_id}/ssh",
    )
    with pytest.raises(SecretError):
        ProtectedStagingSecretAuthority.validate_target(target)


def test_live_secret_reference_cannot_replace_staging_reference() -> None:
    context = require_merged_main_context(buildkite_environment())
    authority = authority_from_environment(context, authority_environment())
    payload = authority.model_dump()
    payload["cisco"]["credential_reference"] = "openbao:kv-v2:ncdp/devices/1/ssh"
    with pytest.raises(ValidationError, match="staging domain authority changed"):
        authority.__class__.model_validate(payload)


def test_buildkite_wrapper_keeps_pipeline_frozen() -> None:
    root = Path(__file__).parents[1]
    pipeline = (root / ".buildkite/pipeline.yml").read_text(encoding="utf-8")
    assert "key: cml-staging" in pipeline
    assert 'if: "false"' in pipeline
    assert (
        'if: false && build.branch == "main" && build.pull_request.id == null'
        in pipeline
    )
