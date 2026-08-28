"""CML realization admission for management-service reachability telemetry."""

from __future__ import annotations

import hashlib
import os
import ssl
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.audit import Sha256, canonical_json_bytes
from network_change_delivery.observability_private_paths import (
    ObservabilityPrivatePathError,
    ensure_private_tree,
    validate_observability_root,
    validate_private_file,
)

LEGACY_LAB_ID = "09605569-0468-4fc4-8684-beb5a1342b9c"
OPERATOR_LAB_TITLE = "NCDP Terraform Twin"
STAGING_LAB_PREFIX = "NCDP Staging "
ADMISSION_TTL = timedelta(minutes=15)
EXPECTED_NODES = {
    "netbox:dcim.device:1": {
        "name": "core-02",
        "address": "192.168.4.14",
        "definition": "cat8000v",
        "image": "cat8000v-17-18-02",
    },
    "netbox:dcim.device:2": {
        "name": "edge-junos-01",
        "address": "192.168.4.20",
        "definition": "vjunos-router",
        "image": "vjunos-router-23-2r1-15",
    },
}
_UUID_PATTERN = r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$"


class ObservabilityRealizationError(ValueError):
    """Bounded CML authority/admission failure."""


class RealizationNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    inventory_object_id: Literal["netbox:dcim.device:1", "netbox:dcim.device:2"]
    stable_name: Literal["core-02", "edge-junos-01"]
    cml_node_id: str = Field(pattern=_UUID_PATTERN)
    management_ip: Literal["192.168.4.14", "192.168.4.20"]
    node_definition: Literal["cat8000v", "vjunos-router"]
    image_definition: Literal["cat8000v-17-18-02", "vjunos-router-23-2r1-15"]
    state: Literal["BOOTED"] = "BOOTED"


class RealizationAdmission(BaseModel):
    """Private, expiring authorization for one exact operator realization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    lab_id: str = Field(pattern=_UUID_PATTERN)
    lab_title: Literal["NCDP Terraform Twin"] = "NCDP Terraform Twin"
    admitted_at: datetime
    expires_at: datetime
    legacy_lab_state: Literal["STOPPED"] = "STOPPED"
    staging_labs: tuple[()] = ()
    nodes: tuple[RealizationNode, RealizationNode]
    digest: Sha256

    @model_validator(mode="after")
    def exact_admission(self) -> RealizationAdmission:
        identities = tuple(item.inventory_object_id for item in self.nodes)
        if (
            self.admitted_at.tzinfo is None
            or self.admitted_at.utcoffset() is None
            or self.expires_at <= self.admitted_at
            or identities != tuple(EXPECTED_NODES)
        ):
            raise ValueError("observability realization admission rejected")
        for node in self.nodes:
            expected = EXPECTED_NODES[node.inventory_object_id]
            if (
                node.stable_name != expected["name"]
                or node.management_ip != expected["address"]
                or node.node_definition != expected["definition"]
                or node.image_definition != expected["image"]
            ):
                raise ValueError("observability realization admission rejected")
        if self.digest != self.calculated_digest():
            raise ValueError("observability realization digest rejected")
        return self

    def calculated_digest(self) -> str:
        content = canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))
        return f"sha256:{hashlib.sha256(content).hexdigest()}"


class CmlRealizationAuthority:
    """Read-only exact CML API boundary for one operator realization."""

    def __init__(
        self,
        address: str,
        certificate: str,
        username: str,
        password: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        try:
            parsed = urlparse(address)
        except ValueError:
            raise ObservabilityRealizationError("CML authority rejected") from None
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or not certificate
            or not username
            or not password
        ):
            raise ObservabilityRealizationError("CML authority rejected")
        try:
            context = ssl.create_default_context(cadata=certificate)
            self._client = httpx.Client(
                base_url=address.rstrip("/"),
                verify=context,
                timeout=httpx.Timeout(20, connect=5),
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            )
        except (OSError, ValueError):
            raise ObservabilityRealizationError("CML authority rejected") from None
        try:
            response = self._client.post(
                "/api/v0/authenticate",
                json={"username": username, "password": password},
            )
            if response.status_code != 200:
                raise ObservabilityRealizationError("CML authentication failed")
            payload = response.json()
            token = payload if isinstance(payload, str) else payload.get("token")
        except (httpx.HTTPError, ValueError):
            raise ObservabilityRealizationError("CML authentication failed") from None
        if not isinstance(token, str) or not token:
            raise ObservabilityRealizationError("CML authentication failed")
        self._client.headers["Authorization"] = f"Bearer {token}"

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str) -> Any:
        try:
            response = self._client.get(path)
            if response.status_code != 200 or len(response.content) > 2 * 1024 * 1024:
                raise ObservabilityRealizationError("CML authority unavailable")
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise ObservabilityRealizationError("CML authority unavailable") from None

    def _configuration(self, lab_id: str, node_id: str) -> str:
        for suffix in ("configuration", "configurations"):
            try:
                response = self._client.get(
                    f"/api/v0/labs/{lab_id}/nodes/{node_id}/{suffix}"
                )
            except httpx.HTTPError:
                continue
            if response.status_code != 200:
                continue
            if len(response.content) > 2 * 1024 * 1024:
                raise ObservabilityRealizationError("CML Day-0 identity unavailable")
            try:
                payload = response.json()
            except ValueError:
                continue
            if isinstance(payload, str):
                return payload
            if isinstance(payload, dict):
                value = payload.get("configuration") or payload.get(
                    "config/juniper.conf"
                )
                if isinstance(value, str):
                    return value
            if isinstance(payload, list):
                return self._list_configuration(payload)
        node = self._get(f"/api/v0/labs/{lab_id}/nodes/{node_id}")
        if isinstance(node, dict):
            configuration = node.get("configuration")
            if isinstance(configuration, str):
                return configuration
            if isinstance(configuration, list):
                return self._list_configuration(configuration)
        raise ObservabilityRealizationError("CML Day-0 identity unavailable")

    @staticmethod
    def _list_configuration(payload: list[Any]) -> str:
        """Read the single CML 2.10 stored-configuration entry."""
        if len(payload) != 1 or not isinstance(payload[0], dict):
            raise ObservabilityRealizationError("CML Day-0 identity unavailable")
        content = payload[0].get("content")
        if not isinstance(content, str) or not content:
            raise ObservabilityRealizationError("CML Day-0 identity unavailable")
        return content

    def admit(
        self,
        lab_id: str,
        node_ids: dict[str, str],
        *,
        now: datetime | None = None,
    ) -> RealizationAdmission:
        """Validate ownership, collision absence, Day-0 identity, and BOOTED state."""
        if set(node_ids) != set(EXPECTED_NODES):
            raise ObservabilityRealizationError("CML node population rejected")
        lab_ids = self._get("/api/v0/labs")
        if not isinstance(lab_ids, list) or any(
            not isinstance(item, str) for item in lab_ids
        ):
            raise ObservabilityRealizationError("CML lab population rejected")
        operator_matches: list[str] = []
        legacy_seen = False
        for candidate in lab_ids:
            lab = self._get(f"/api/v0/labs/{candidate}")
            if not isinstance(lab, dict):
                raise ObservabilityRealizationError("CML lab population rejected")
            title = lab.get("lab_title") or lab.get("title")
            if title == OPERATOR_LAB_TITLE:
                operator_matches.append(candidate)
            if isinstance(title, str) and title.startswith(STAGING_LAB_PREFIX):
                raise ObservabilityRealizationError("CML staging realization active")
            if candidate == LEGACY_LAB_ID:
                legacy_seen = True
                legacy_nodes = self._get(f"/api/v0/labs/{candidate}/nodes")
                if not isinstance(legacy_nodes, list):
                    raise ObservabilityRealizationError("legacy CML state rejected")
                for legacy_node_id in legacy_nodes:
                    legacy_node = self._get(
                        f"/api/v0/labs/{candidate}/nodes/{legacy_node_id}"
                    )
                    if not isinstance(legacy_node, dict) or legacy_node.get(
                        "state"
                    ) not in {
                        "STOPPED",
                        "DEFINED_ON_CORE",
                    }:
                        raise ObservabilityRealizationError(
                            "legacy CML realization active"
                        )
            elif candidate != lab_id:
                foreign_nodes = self._get(f"/api/v0/labs/{candidate}/nodes")
                if not isinstance(foreign_nodes, list):
                    raise ObservabilityRealizationError(
                        "CML address ownership ambiguous"
                    )
                for foreign_node_id in foreign_nodes:
                    foreign_node = self._get(
                        f"/api/v0/labs/{candidate}/nodes/{foreign_node_id}"
                    )
                    if not isinstance(foreign_node, dict):
                        raise ObservabilityRealizationError(
                            "CML address ownership ambiguous"
                        )
                    if foreign_node.get("state") in {"BOOTED", "STARTED"}:
                        configuration = self._configuration(candidate, foreign_node_id)
                        if any(
                            expected["address"] in configuration
                            for expected in EXPECTED_NODES.values()
                        ):
                            raise ObservabilityRealizationError(
                                "CML address ownership ambiguous"
                            )
        if operator_matches != [lab_id] or not legacy_seen:
            raise ObservabilityRealizationError("CML operator realization rejected")

        actual_ids = self._get(f"/api/v0/labs/{lab_id}/nodes")
        if not isinstance(actual_ids, list):
            raise ObservabilityRealizationError("CML node population rejected")
        nodes: list[RealizationNode] = []
        for identity, expected in EXPECTED_NODES.items():
            node_id = node_ids[identity]
            if node_id not in actual_ids:
                raise ObservabilityRealizationError("CML node identity rejected")
            node = self._get(f"/api/v0/labs/{lab_id}/nodes/{node_id}")
            if not isinstance(node, dict):
                raise ObservabilityRealizationError("CML node identity rejected")
            configuration = self._configuration(lab_id, node_id)
            image = node.get("image_definition") or node.get("image_definition_id")
            if (
                node.get("label") != expected["name"]
                or node.get("node_definition") != expected["definition"]
                or image != expected["image"]
                or node.get("state") != "BOOTED"
                or expected["name"] not in configuration
                or expected["address"] not in configuration
            ):
                raise ObservabilityRealizationError("CML node admission rejected")
            nodes.append(
                RealizationNode(
                    inventory_object_id=identity,
                    stable_name=expected["name"],
                    cml_node_id=node_id,
                    management_ip=expected["address"],
                    node_definition=expected["definition"],
                    image_definition=expected["image"],
                )
            )
        admitted = (now or datetime.now(UTC)).astimezone(UTC)
        unsigned = RealizationAdmission.model_construct(
            schema_version="1",
            lab_id=lab_id,
            lab_title=OPERATOR_LAB_TITLE,
            admitted_at=admitted,
            expires_at=admitted + ADMISSION_TTL,
            legacy_lab_state="STOPPED",
            staging_labs=(),
            nodes=tuple(nodes),
            digest="sha256:" + "0" * 64,
        )
        return RealizationAdmission.model_validate(
            {
                **unsigned.model_dump(mode="json", exclude={"digest"}),
                "digest": unsigned.calculated_digest(),
            }
        )


def publish_admission(root: Path, admission: RealizationAdmission) -> Path:
    """Atomically publish one canonical private admission record."""
    validate_observability_root(root)
    ensure_private_tree(root, "operator", "control")
    path = root / "operator/realization.json"
    content = canonical_json_bytes(admission.model_dump(mode="json"))
    descriptor, name = tempfile.mkstemp(prefix=".realization.", dir=path.parent)
    temporary = Path(name)
    replaced = False
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, content)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        temporary.replace(path)
        replaced = True
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as error:
        if replaced:
            raise ObservabilityRealizationError(
                "realization publication outcome ambiguous"
            ) from error
        raise ObservabilityRealizationError("realization publication failed") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return path


def read_admission(root: Path, *, now: datetime | None = None) -> RealizationAdmission:
    try:
        content = validate_private_file(root / "operator/realization.json")
        assert content is not None
        admission = RealizationAdmission.model_validate_json(content)
    except (ValueError, ObservabilityPrivatePathError):
        raise ObservabilityRealizationError("realization admission rejected") from None
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if admission.expires_at <= current:
        raise ObservabilityRealizationError("realization admission expired")
    return admission


def retire_admission(root: Path) -> None:
    """Remove only the realization authorization after target retirement."""
    path = root / "operator/realization.json"
    path.unlink(missing_ok=True)
    if path.parent.exists():
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
