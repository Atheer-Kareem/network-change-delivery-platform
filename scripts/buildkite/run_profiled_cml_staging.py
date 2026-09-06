#!/usr/bin/env python3
"""Buildkite authority and publication around the accepted profiled lifecycle."""

from __future__ import annotations

import io
import logging
import os
import re
import ssl
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import httpx

from network_change_delivery.buildkite_identity import read_buildkite_oidc_jwt
from network_change_delivery.buildkite_staging import (
    OPENBAO_STAGING_AUDIENCE,
    BuildkiteStagingContext,
    BuildkiteStagingSecretProvider,
    reject_ambient_staging_authority,
    staging_context_from_environment,
    validate_staging_state_root,
)
from network_change_delivery.profile_inventory import NetBoxProfileInventoryProvider
from network_change_delivery.profiled_staging import (
    PROFILED_STAGING_DEVICE_NAMES,
    ProfiledStagingError,
    ProfiledStagingEvidence,
    ProfiledStagingLifecycle,
    ProfiledStagingOutcome,
    validate_private_run_directory,
    validate_profiled_staging_evidence_path,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from run_profiled_cml_staging import LocalTerraformOperations  # noqa: E402

_PROTECTED_NAMES = (
    "NCDP_STAGING_NETBOX_TOKEN",
    "NCDP_CML_STAGING_USERNAME",
    "NCDP_CML_STAGING_PASSWORD",
)
_REQUIRED_NAMES = (
    "NCDP_BUILDKITE_PIPELINE_ID",
    "NCDP_STAGING_STATE_ROOT",
    "NCDP_NETBOX_URL",
    "NCDP_OPENBAO_URL",
    "CML2_ADDRESS",
    "CML2_CACERT",
    *_PROTECTED_NAMES,
)
_PHASES = (
    "create_outcome",
    "start_outcome",
    "transit_recycle_outcome",
    "read_only_outcome",
    "destroy_outcome",
    "absence_verification",
    "state_retirement",
)


def command(arguments: list[str], *, cwd: Path = ROOT, stdin: str | None = None):
    """Capture tool output; secret-bearing failures never become ordinary logs."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in (*_PROTECTED_NAMES, "CML2_TOKEN")
    }
    result = subprocess.run(
        arguments,
        cwd=cwd,
        env=environment,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode:
        raise ProfiledStagingError("Buildkite staging helper failed")
    return result.stdout


def admit() -> tuple[BuildkiteStagingContext, Path]:
    context = staging_context_from_environment()
    # Require an explicit zero even though the reusable historical context
    # loader accepts an absent count as zero.
    if os.environ.get("BUILDKITE_RETRY_COUNT") != "0":
        raise ProfiledStagingError("Buildkite staging retry context rejected")
    reject_ambient_staging_authority()
    if any(not os.environ.get(name) for name in _REQUIRED_NAMES):
        raise ProfiledStagingError("Buildkite staging protected configuration missing")
    if context.pipeline_id != os.environ["NCDP_BUILDKITE_PIPELINE_ID"]:
        raise ProfiledStagingError("Buildkite staging pipeline identity rejected")
    root = validate_staging_state_root(
        Path(os.environ["NCDP_STAGING_STATE_ROOT"]), ROOT
    )
    command(["scripts/buildkite/verify_commit.sh"])
    return context, root


def authenticate_cml(*, transport: httpx.BaseTransport | None = None) -> str:
    """Mint one memory-only bearer using the documented personal-license exception."""
    address = httpx.URL(os.environ["CML2_ADDRESS"])
    if (
        address.scheme != "https"
        or not address.host
        or address.userinfo
        or address.query
        or address.fragment
        or address.path != "/"
    ):
        raise ProfiledStagingError("Buildkite staging CML endpoint rejected")
    try:
        tls = ssl.create_default_context(cadata=os.environ["CML2_CACERT"])
        with httpx.Client(
            base_url=address,
            verify=tls,
            transport=transport,
            timeout=20,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            response = client.post(
                "/api/v0/authenticate",
                json={
                    "username": os.environ["NCDP_CML_STAGING_USERNAME"],
                    "password": os.environ["NCDP_CML_STAGING_PASSWORD"],
                },
            )
            if response.status_code != 200:
                raise ProfiledStagingError("Buildkite staging CML login rejected")
            payload = response.json()
            token = payload if isinstance(payload, str) else payload.get("token")
            if not isinstance(token, str) or not re.fullmatch(
                r"[A-Za-z0-9._~-]{1,8192}", token
            ):
                raise ProfiledStagingError("Buildkite staging CML bearer rejected")
            return token
    except (httpx.HTTPError, ValueError, AttributeError, ssl.SSLError):
        raise ProfiledStagingError("Buildkite staging CML login failed") from None


def evidence_succeeded(
    evidence: ProfiledStagingEvidence, context: BuildkiteStagingContext
) -> bool:
    """Require all authoritative schema-v2 success facts, not just an outcome label."""
    return (
        evidence.final_outcome is ProfiledStagingOutcome.SUCCEEDED
        and evidence.source_commit == context.commit
        and evidence.staging_run_id == context.staging_run_id
        and evidence.build_id == context.build_id
        and evidence.orchestrator == "buildkite"
        and evidence.lab_title == f"NCDP Staging {context.staging_run_id}"
        and evidence.lab_id is not None
        and evidence.lab_start_evidence is not None
        and evidence.lab_start_evidence.identity
        == f"staging-lab-start:{context.staging_run_id}"
        and evidence.topology_digest is not None
        and evidence.context_digest is not None
        and evidence.trust_generation is not None
        and evidence.trust_generation.identity
        == f"staging-trust:{context.staging_run_id}"
        and evidence.transit_recycle_evidence is not None
        and evidence.transit_recycle_evidence.identity
        == f"staging-transit-recycle:{context.staging_run_id}:transit-ios-01"
        and all(getattr(evidence, phase) == "succeeded" for phase in _PHASES)
        and evidence.primary_failure is None
        and evidence.cleanup_failure is None
        and tuple(item.logical_name for item in evidence.readiness)
        == PROFILED_STAGING_DEVICE_NAMES
        and all(item.outcome.value == "READY" for item in evidence.readiness)
        and tuple(item.device_identity for item in evidence.devices)
        == tuple(f"netbox:dcim.device:{number}" for number in (1, 2, 8, 9))
        and tuple(item.logical_name for item in evidence.devices)
        == PROFILED_STAGING_DEVICE_NAMES
        and all(item.read_only_collection == "succeeded" for item in evidence.devices)
        and all(
            ready.device_identity == device.device_identity
            and ready.automation_profile_id == device.automation_profile_id
            and ready.cml_realization_profile_id == device.cml_realization_profile_id
            and ready.cml_node_id == device.cml_node_id
            and ready.readiness_evidence == device.readiness_evidence
            for ready, device in zip(evidence.readiness, evidence.devices, strict=True)
        )
    )


_TIMING_LABELS = {
    "create": "Infrastructure create",
    "start": "CML lab start",
    "transit_first_boot": "Transit first boot",
    "transit_persistence": "Day-0 persistence hold",
    "transit_stop": "Transit stop",
    "transit_second_boot": "Transit second boot",
    "readiness": "Service readiness",
    "read_only": "Read-only validation",
    "cleanup": "Cleanup",
    "lifecycle_total": "Total lifecycle",
}


def failed_phase(evidence: ProfiledStagingEvidence) -> str:
    """Infer a closed primary-phase label, never parse exception/provider text."""
    if evidence.create_outcome == "not_attempted":
        return "admission"
    if (
        evidence.create_outcome != "succeeded"
        or evidence.start_outcome == "not_attempted"
    ):
        return "infrastructure create"
    if evidence.start_outcome != "succeeded":
        return "CML lab start"
    if evidence.transit_recycle_outcome != "succeeded":
        return "transit recycle"
    if len(evidence.readiness) != 4 or any(
        item.outcome.value != "READY" for item in evidence.readiness
    ):
        return "service readiness"
    if evidence.trust_generation is None:
        return "strict trust"
    return "read-only validation"


def summary(evidence: ProfiledStagingEvidence, *, succeeded: bool) -> str:
    """Render only closed labels and counts; never render raw failure/provider text."""
    lines = [
        "Profiled exact-four CML staging: " + ("SUCCEEDED" if succeeded else "FAILED"),
        "",
    ]
    if evidence.primary_failure:
        lines.append(f"Failed phase: {failed_phase(evidence)}")
    if evidence.cleanup_failure:
        lines.append("Failed phase: cleanup")
    for phase in _PHASES:
        state = getattr(evidence, phase)
        safe = (
            state
            if state in {"succeeded", "attempted", "not_attempted"}
            else "incomplete"
        )
        lines.append(f"- {phase}: {safe}")
    ready = sum(item.outcome.value == "READY" for item in evidence.readiness)
    validated = sum(
        item.read_only_collection == "succeeded" for item in evidence.devices
    )
    for name in PROFILED_STAGING_DEVICE_NAMES:
        observation = next(
            (item for item in evidence.readiness if item.logical_name == name), None
        )
        ready_state = observation.outcome.value if observation else "not_completed"
        elapsed = f" ({observation.elapsed_seconds:.1f}s)" if observation else ""
        collected = any(
            item.logical_name == name and item.read_only_collection == "succeeded"
            for item in evidence.devices
        )
        lines.append(
            f"- {name}: {ready_state}{elapsed}; READ-ONLY "
            + ("succeeded" if collected else "not_completed")
        )
    lines.extend(
        (
            f"- READY: {ready}/4; READ-ONLY validated: {validated}/4",
            f"- primary failure: {'present' if evidence.primary_failure else 'none'}",
            f"- cleanup failure: {'present' if evidence.cleanup_failure else 'none'}",
            "- CML recycle scope: transit-ios-01 only; no device CLI writes",
        )
    )
    if evidence.timings_seconds:
        lines.extend(("", "Timing (seconds; total includes nested phases):"))
        for phase, label in _TIMING_LABELS.items():
            if phase in evidence.timings_seconds:
                lines.append(f"- {label}: {evidence.timings_seconds[phase]:.1f}s")
    return "\n".join(lines) + "\n"


def run(context: BuildkiteStagingContext, root: Path) -> int:
    run_id = context.staging_run_id
    runs = root / "ephemeral"
    evidence_root = root / "evidence"
    for directory in (runs, evidence_root):
        directory.mkdir(mode=0o700, exist_ok=True)
        validate_private_run_directory(directory, ROOT)
    run_directory = runs / run_id
    # Both are create-only. A repeated build cannot reuse retained mutable state.
    evidence_path = validate_profiled_staging_evidence_path(
        evidence_root / f"{run_id}.json", run_directory
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(evidence_path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        run_directory.mkdir(mode=0o700)
        validate_private_run_directory(run_directory, ROOT)
        inventory = NetBoxProfileInventoryProvider(
            url=os.environ["NCDP_NETBOX_URL"],
            token=os.environ["NCDP_STAGING_NETBOX_TOKEN"],
        )
        jwt = read_buildkite_oidc_jwt(
            io.StringIO(
                command(
                    [
                        "buildkite-agent",
                        "oidc",
                        "request-token",
                        "--audience",
                        OPENBAO_STAGING_AUDIENCE,
                        "--lifetime",
                        "300",
                        "--subject-claim",
                        "pipeline_id",
                        "--claim",
                        "build_id",
                    ]
                )
            )
        )
        secrets = BuildkiteStagingSecretProvider(
            jwt, context, url=os.environ["NCDP_OPENBAO_URL"]
        )
        token = authenticate_cml()
        # Providers own the remaining in-memory credentials. Child processes
        # receive no operator password or NetBox token. Only Terraform gets
        # CML2_TOKEN through LocalTerraformOperations._environment().
        for name in _PROTECTED_NAMES:
            os.environ.pop(name, None)
        operations = LocalTerraformOperations(
            run_id,
            run_directory,
            inventory=inventory,
            secrets=secrets,
            cml_token=token,
        )
        with (
            Path(os.devnull).open("w") as quiet,
            redirect_stdout(quiet),
            redirect_stderr(quiet),
        ):
            evidence = ProfiledStagingLifecycle(run_id, "buildkite", operations).run()
        # The lifecycle preserves separate failures; publication excludes raw
        # exception text because unexpected library errors may contain secrets.
        evidence = ProfiledStagingEvidence.model_validate(
            evidence.model_dump(mode="python")
            | {
                "build_id": context.build_id,
                "primary_failure": "staging operation failed"
                if evidence.primary_failure
                else None,
                "cleanup_failure": "cleanup failed; retained state requires review"
                if evidence.cleanup_failure
                else None,
            }
        )
        output.write(evidence.model_dump_json(indent=2) + "\n")
        output.flush()
        os.fsync(output.fileno())
    succeeded = evidence_succeeded(evidence, context)
    rendered = summary(evidence, succeeded=succeeded)
    print(rendered, end="")
    try:
        # Publish the bounded summary only. Full schema-v2 evidence remains in
        # the agent-owned external evidence directory, never the run/state tree.
        command(
            [
                "buildkite-agent",
                "annotate",
                "--style",
                "success" if succeeded else "error",
                "--context",
                "cml-staging",
            ],
            stdin=rendered,
        )
    except Exception:
        print("Staging summary publication failed", file=sys.stderr)
        return 3 if succeeded else 2
    return 0 if succeeded else 2


def main() -> int:
    logging.disable(logging.CRITICAL)
    os.umask(0o077)
    try:
        context, root = admit()
        return run(context, root)
    except Exception:
        # No exception repr, HTTP body, Terraform output, or credential value.
        print(
            "Buildkite profiled staging failed; retain external state for review",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
