"""Fail-closed, metadata-only control of the loopback Oxidized API."""

from __future__ import annotations

import fcntl
import os
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from network_change_delivery.oxidized_private_paths import (
    ensure_private_directory,
    validate_private_file,
)

EXPECTED_NODES = frozenset({"netbox-device-1", "netbox-device-2"})
CONTROL_GROUP = "managed"
API_MAX_BYTES = 64 * 1024
HTTP_TIMEOUT = 3.0
DEFAULT_DEADLINE = 120.0
POLL_INTERVAL = 1.0


class OxidizedControlError(ValueError):
    """Bounded controller failure with no raw API or configuration content."""


class CollectionOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    COLLECTION_FAILED = "COLLECTION_FAILED"
    COLLECTION_TIMED_OUT = "COLLECTION_TIMED_OUT"
    CONCURRENT_COLLECTION = "CONCURRENT_COLLECTION"
    INCONSISTENT_EVIDENCE = "INCONSISTENT_EVIDENCE"


class CollectionReady(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    refreshed_at: datetime
    expires_at: datetime
    nodes: tuple[Literal["netbox-device-1", "netbox-device-2"], ...]
    container_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    service_contract: Literal["10C-5"] = "10C-5"

    @field_validator("refreshed_at", "expires_at")
    @classmethod
    def utc_only(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("readiness timestamps must be UTC")
        return value


class _LastJob(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    start: datetime
    end: datetime
    status: str = Field(min_length=1, max_length=32)

    @field_validator("start", "end")
    @classmethod
    def utc_only(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("job timestamp rejected")
        return value


class _Node(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    name: str
    group: str
    status: str
    last: _LastJob | None


class CollectionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request_id: uuid.UUID
    requested_at: datetime
    completed_at: datetime | None = None
    node: str
    outcome: CollectionOutcome
    upstream_status: str | None = Field(default=None, max_length=32)


def validate_loopback_api_url(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.port is None
    ):
        raise OxidizedControlError("Oxidized API endpoint rejected")
    return url.rstrip("/")


def read_collection_ready(
    path: Path, container_id: str, *, now: datetime | None = None
) -> CollectionReady:
    try:
        validate_private_file(path)
        if path.stat().st_size > 4096:
            raise OxidizedControlError("Oxidized collection readiness rejected")
        marker = CollectionReady.model_validate_json(path.read_bytes())
    except (OSError, ValidationError, ValueError):
        raise OxidizedControlError("Oxidized collection readiness rejected") from None
    current = now or datetime.now(UTC)
    if (
        marker.expires_at <= current
        or marker.refreshed_at > current
        or set(marker.nodes) != EXPECTED_NODES
        or len(marker.nodes) != 2
        or marker.container_id != container_id
    ):
        raise OxidizedControlError("Oxidized collection readiness rejected")
    return marker


class OxidizedController:
    def __init__(
        self,
        api_url: str,
        readiness_path: Path,
        lock_root: Path,
        container_id: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._url = validate_loopback_api_url(api_url)
        self._readiness_path = readiness_path
        self._lock_root = lock_root
        self._container_id = container_id
        self._client = httpx.Client(
            timeout=HTTP_TIMEOUT,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def _nodes(self) -> dict[str, _Node]:
        try:
            response = self._client.get(f"{self._url}/nodes.json")
            if response.status_code != 200 or len(response.content) > API_MAX_BYTES:
                raise OxidizedControlError("Oxidized node status unavailable")
            payload = response.json()
            nodes = tuple(_Node.model_validate(item) for item in payload)
        except (httpx.HTTPError, ValueError, ValidationError, TypeError):
            raise OxidizedControlError("Oxidized node status unavailable") from None
        mapped = {node.name: node for node in nodes}
        if (
            len(nodes) != 2
            or set(mapped) != EXPECTED_NODES
            or any(node.group != CONTROL_GROUP for node in nodes)
        ):
            raise OxidizedControlError("Oxidized node population rejected")
        return mapped

    @contextmanager
    def _lock(self, node: str) -> Iterator[bool]:
        try:
            ensure_private_directory(self._lock_root)
            lock_path = self._lock_root / f"{node}.lock"
            flags = os.O_RDWR | os.O_CREAT
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(lock_path, flags, 0o600)
            validate_private_file(lock_path)
        except (OSError, ValueError):
            raise OxidizedControlError("Oxidized collection lock rejected") from None
        acquired = False
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                pass
            yield acquired
        finally:
            if acquired:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def collect(
        self, node: str, *, deadline_seconds: float = DEFAULT_DEADLINE
    ) -> CollectionResult:
        if (
            node not in EXPECTED_NODES
            or deadline_seconds <= 0
            or deadline_seconds > DEFAULT_DEADLINE
        ):
            raise OxidizedControlError("Oxidized collection request rejected")
        request_id = uuid.uuid4()
        requested_at = datetime.now(UTC)
        with self._lock(node) as acquired:
            if not acquired:
                return CollectionResult(
                    request_id=request_id,
                    requested_at=requested_at,
                    node=node,
                    outcome=CollectionOutcome.CONCURRENT_COLLECTION,
                )
            read_collection_ready(
                self._readiness_path, self._container_id, now=requested_at
            )
            before = self._nodes()[node].last
            try:
                response = self._client.put(
                    f"{self._url}/node/next/{node}.json",
                    json={
                        "user": "NCDP Oxidized",
                        "email": "oxidized@ncdp.local",
                        "msg": f"Observation {request_id}",
                    },
                )
            except httpx.HTTPError:
                raise OxidizedControlError(
                    "Oxidized collection submission failed"
                ) from None
            if response.status_code != 200 or len(response.content) > 1024:
                raise OxidizedControlError("Oxidized collection submission failed")
            deadline = time.monotonic() + deadline_seconds
            saw_transition = False
            while time.monotonic() < deadline:
                current = self._nodes()[node].last
                if current is None:
                    saw_transition = True
                elif current != before:
                    if current.start < requested_at or current.end < current.start:
                        return CollectionResult(
                            request_id=request_id,
                            requested_at=requested_at,
                            completed_at=current.end,
                            node=node,
                            outcome=CollectionOutcome.INCONSISTENT_EVIDENCE,
                            upstream_status=current.status,
                        )
                    if saw_transition or before is None or current != before:
                        outcome = (
                            CollectionOutcome.SUCCEEDED
                            if current.status == "success"
                            else CollectionOutcome.COLLECTION_FAILED
                        )
                        return CollectionResult(
                            request_id=request_id,
                            requested_at=requested_at,
                            completed_at=current.end,
                            node=node,
                            outcome=outcome,
                            upstream_status=current.status,
                        )
                time.sleep(POLL_INTERVAL)
            return CollectionResult(
                request_id=request_id,
                requested_at=requested_at,
                node=node,
                outcome=CollectionOutcome.COLLECTION_TIMED_OUT,
            )
