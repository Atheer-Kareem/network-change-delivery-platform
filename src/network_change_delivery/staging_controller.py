"""Merged-main controller for the disposable ADR 0023 staging lab."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from network_change_delivery.buildkite_identity import read_buildkite_oidc_jwt
from network_change_delivery.buildkite_staging import (
    BuildkiteStagingContext,
    staging_context_from_environment,
    validate_staging_state_root,
)
from network_change_delivery.protected_staging import (
    BROWNFIELD_LAB_UUID,
    EXPECTED_TERRAFORM_ADDRESSES,
    LIFECYCLE_ADDRESS,
    LIVE_DENY_IDS,
    LIVE_DENY_IPS,
    CMLAuthority,
    ProtectedCMLClient,
    ProtectedCMLCredentials,
    ProtectedStagingError,
    ProtectedStagingInventoryResolver,
    ProtectedTerraformExecutor,
    StagingTargetAuthority,
    SubprocessTerraformRunner,
)
from network_change_delivery.protected_staging_runtime import (
    LifecycleIdentity,
    ProtectedCommandRunner,
    ProtectedNCDPReadOnlyValidator,
    ProtectedReadinessProbe,
    ProtectedRuntimeOperations,
    ProtectedSSHHostTrust,
    build_cml_ssl_context,
    build_protected_terraform_environment,
    derive_junos_password_verifier,
    derive_run_directory,
    load_protected_staging_credentials,
    run_protected_lifecycle,
)


class StagingDomainAuthority(BaseModel):
    """Only the domain authority needed by disposable lab staging."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1
    source_commit: str
    netbox_url: str
    openbao_url: str
    cisco: StagingTargetAuthority
    junos: StagingTargetAuthority
    live_deny_device_ids: tuple[int, ...] = (1, 2, 3)
    live_deny_management_ips: tuple[str, ...] = (
        "192.168.4.14",
        "192.168.4.15",
        "192.168.4.20",
    )
    cml: CMLAuthority
    terraform_addresses: tuple[str, ...]
    lifecycle_update_address: str = LIFECYCLE_ADDRESS

    @model_validator(mode="after")
    def exact_domain_authority(self) -> StagingDomainAuthority:
        if (
            {self.cisco.device_id, self.junos.device_id} != {6, 7}
            or {self.cisco.live_homolog_id, self.junos.live_homolog_id} != {1, 2}
            or {self.cisco.management_ip, self.junos.management_ip}
            != {"192.168.4.30", "192.168.4.31"}
            or set(self.live_deny_device_ids) != LIVE_DENY_IDS
            or set(self.live_deny_management_ips) != LIVE_DENY_IPS
            or set(self.terraform_addresses) != EXPECTED_TERRAFORM_ADDRESSES
            or len(self.terraform_addresses) != 10
            or self.lifecycle_update_address != LIFECYCLE_ADDRESS
            or self.cml.denied_lab_uuids != (BROWNFIELD_LAB_UUID,)
            or self.cisco.openbao_role != "ncdp-buildkite-staging-device-6"
            or self.cisco.credential_reference != "openbao:kv-v2:ncdp/devices/6/ssh"
            or self.junos.openbao_role != "ncdp-buildkite-staging-device-7"
            or self.junos.credential_reference != "openbao:kv-v2:ncdp/devices/7/ssh"
        ):
            raise ValueError("staging domain authority changed")
        return self

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()

    @property
    def bundle_digest(self) -> str:
        return hashlib.sha256(self.source_commit.encode()).hexdigest()


def require_merged_main_context(
    environment: Mapping[str, str] | None = None,
) -> BuildkiteStagingContext:
    """Admit credentialed staging only for a non-PR build of merged main."""
    values = os.environ if environment is None else environment
    context = staging_context_from_environment(values)
    pull_request = values.get("BUILDKITE_PULL_REQUEST", "false")
    if context.branch != "main" or pull_request != "false":
        raise ProtectedStagingError("staging requires reviewed merged main")
    return context


def _target(role: Literal["cisco", "junos"]) -> StagingTargetAuthority:
    common = {
        "site_id": 1,
        "environment": "staging",
        "status": "staged",
        "role_slug": "ncdp-staging",
        "management_interface_type": "1000base-t",
        "management_interface_enabled": True,
        "management_interface_mgmt_only": False,
    }
    values = {
        "cisco": {
            "device_id": 6,
            "name": "stg-core-02",
            "device_type_id": 1,
            "platform_slug": "cisco-ios-xe",
            "management_interface": "GigabitEthernet1",
            "management_interface_id": 9,
            "management_ip_address_id": 9,
            "management_cidr": "192.168.4.30/24",
            "management_ip": "192.168.4.30",
            "live_homolog_id": 1,
            "live_homolog_name": "core-02",
            "live_primary_cidr": "192.168.4.14/24",
            "openbao_role": "ncdp-buildkite-staging-device-6",
            "credential_reference": "openbao:kv-v2:ncdp/devices/6/ssh",
        },
        "junos": {
            "device_id": 7,
            "name": "stg-edge-junos-01",
            "device_type_id": 2,
            "platform_slug": "juniper-junos",
            "management_interface": "fxp0",
            "management_interface_id": 10,
            "management_ip_address_id": 10,
            "management_cidr": "192.168.4.31/24",
            "management_ip": "192.168.4.31",
            "live_homolog_id": 2,
            "live_homolog_name": "edge-junos-01",
            "live_primary_cidr": "192.168.4.20/24",
            "openbao_role": "ncdp-buildkite-staging-device-7",
            "credential_reference": "openbao:kv-v2:ncdp/devices/7/ssh",
        },
    }[role]
    return StagingTargetAuthority.model_validate(common | values)


def authority_from_environment(
    context: BuildkiteStagingContext, environment: Mapping[str, str]
) -> StagingDomainAuthority:
    required = {
        name: environment.get(name, "").strip()
        for name in (
            "NCDP_NETBOX_URL",
            "NCDP_OPENBAO_URL",
            "CML2_ADDRESS",
            "CML2_CACERT",
        )
    }
    if not all(required.values()):
        raise ProtectedStagingError("staging authority configuration missing")
    ca_digest = hashlib.sha256(required["CML2_CACERT"].encode()).hexdigest()
    return StagingDomainAuthority(
        source_commit=context.commit,
        netbox_url=required["NCDP_NETBOX_URL"],
        openbao_url=required["NCDP_OPENBAO_URL"],
        cisco=_target("cisco"),
        junos=_target("junos"),
        cml=CMLAuthority(
            controller_identity=required["CML2_ADDRESS"],
            controller_url=required["CML2_ADDRESS"],
            ca_pem_sha256=ca_digest,
        ),
        terraform_addresses=tuple(sorted(EXPECTED_TERRAFORM_ADDRESSES)),
    )


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value:
        raise ProtectedStagingError("staging credential configuration missing")
    return value


def run(environment: Mapping[str, str] | None = None) -> str:
    """Compose and run one exact disposable staging lifecycle."""
    values = dict(os.environ if environment is None else environment)
    for name in (
        "NCDP_NETBOX_TOKEN",
        "CML2_TOKEN",
        "NCDP_DEVICE_USERNAME",
        "NCDP_DEVICE_PASSWORD",
        "NCDP_OPENBAO_ROLE_ID",
        "NCDP_OPENBAO_SECRET_ID",
    ):
        if values.get(name):
            raise ProtectedStagingError("live credential authority is forbidden")
    context = require_merged_main_context(values)
    checkout = Path.cwd().resolve(strict=True)
    authority = authority_from_environment(context, values)
    state_root = validate_staging_state_root(
        Path(_required(values, "NCDP_STAGING_STATE_ROOT")), checkout
    )
    token = _required(values, "NCDP_STAGING_NETBOX_TOKEN")
    username = _required(values, "NCDP_CML_STAGING_USERNAME")
    password = _required(values, "NCDP_CML_STAGING_PASSWORD")
    jwt = read_buildkite_oidc_jwt(sys.stdin)
    resolver = ProtectedStagingInventoryResolver(authority, token)
    targets = resolver.resolve()
    credentials = load_protected_staging_credentials(jwt, context, authority, targets)
    openssl = Path(shutil.which("openssl") or "")
    terraform_binary = Path(shutil.which("terraform") or "")
    ssh_keyscan = Path(shutil.which("ssh-keyscan") or "")
    ssh_keygen = Path(shutil.which("ssh-keygen") or "")
    if not all(
        path.is_absolute() and path.is_file()
        for path in (openssl, terraform_binary, ssh_keyscan, ssh_keygen)
    ):
        raise ProtectedStagingError("staging executable unavailable")
    junos = credentials["stg-edge-junos-01"]
    verifier = derive_junos_password_verifier(
        openssl, junos.password, ProtectedCommandRunner()
    )
    ca_pem = _required(values, "CML2_CACERT")
    cml = ProtectedCMLClient(
        authority.cml,
        ProtectedCMLCredentials(username, password),
        ssl_context=build_cml_ssl_context(ca_pem.encode(), authority),
    )
    cml.authenticate()
    _run_id, run_directory = derive_run_directory(state_root, UUID(context.build_id))
    variables = {
        "TF_VAR_staging_run_id": context.staging_run_id,
        "TF_VAR_lifecycle_state": "DEFINED_ON_CORE",
        "TF_VAR_cisco_bootstrap_hostname": authority.cisco.name,
        "TF_VAR_cisco_bootstrap_management_cidr": authority.cisco.management_cidr,
        "TF_VAR_cisco_bootstrap_username": credentials[authority.cisco.name].username,
        "TF_VAR_cisco_bootstrap_password": credentials[authority.cisco.name].password,
        "TF_VAR_junos_bootstrap_hostname": authority.junos.name,
        "TF_VAR_junos_bootstrap_management_cidr": authority.junos.management_cidr,
        "TF_VAR_junos_bootstrap_username": junos.username,
        "TF_VAR_junos_bootstrap_password_hash": verifier,
    }
    trusted_path = ":".join(
        sorted(
            {
                str(path.parent)
                for path in (openssl, terraform_binary, ssh_keyscan, ssh_keygen)
            }
        )
    )
    terraform_environment = build_protected_terraform_environment(
        terraform_data_dir=run_directory / "terraform-data",
        cml_address=authority.cml.controller_url,
        cml_token=cml.bearer,
        cml_ca_pem=ca_pem,
        variables=variables,
        trusted_path=trusted_path,
    )
    terraform = ProtectedTerraformExecutor(
        checkout,
        run_directory,
        SubprocessTerraformRunner(terraform_binary),
        terraform_environment,
    )
    ansible_root = Path(_required(values, "ANSIBLE_COLLECTIONS_PATH"))
    operations = ProtectedRuntimeOperations(
        manifest=authority,
        run_id=context.staging_run_id,
        run_directory=run_directory,
        resolver=resolver,
        cml=cml,
        terraform=terraform,
        credentials=credentials,
        readiness=ProtectedReadinessProbe(),
        host_trust=ProtectedSSHHostTrust(ssh_keyscan, ssh_keygen),
        validator=ProtectedNCDPReadOnlyValidator(checkout, ssh_keygen, ansible_root),
    )
    evidence = run_protected_lifecycle(
        LifecycleIdentity(
            pipeline_id=UUID(context.pipeline_id),
            build_id=UUID(context.build_id),
            job_id=UUID(context.job_id),
            source_commit=context.commit,
            bundle_digest=authority.bundle_digest,
            manifest_digest=authority.digest,
        ),
        run_directory,
        operations,
    )
    return evidence.safe_json()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        evidence = run()
        arguments.evidence.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            arguments.evidence, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(evidence + "\n")
        return 0 if json.loads(evidence)["overall_result"] == "passed" else 1
    except Exception:
        print("ephemeral staging rejected", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
