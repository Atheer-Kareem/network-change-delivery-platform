"""Append-only persistence for observed-configuration correlation metadata."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from network_change_delivery.audit import NetBoxDeviceIdentity, canonical_json_bytes
from network_change_delivery.audit_store import AuditStore, AuditStoreError
from network_change_delivery.configuration_observation import (
    ConfigurationObservationRecord,
)

MAX_OBSERVATION_RECORD_BYTES = 64 * 1024
MAX_OBSERVATION_RECORD_SCAN = 10_000
MAX_OBSERVATION_QUERY_RESULTS = 100
_DEVICE_IDENTITY_ADAPTER = TypeAdapter(NetBoxDeviceIdentity)


class ConfigurationObservationStore(AuditStore):
    """Typed sibling store for immutable configuration-observation records."""

    def __init__(self, root: Path, *, checkout: Path, create: bool = True) -> None:
        super().__init__(root, checkout=checkout, create=create)
        self._observation_records = self._managed_directory(
            self.root / "observation-records"
        )

    def persist_observation_record(
        self, record: ConfigurationObservationRecord
    ) -> Path:
        """Publish only digest-valid metadata linked to a verified parent audit."""

        self._validate_root_identity()
        record = ConfigurationObservationRecord.model_validate(record)
        if not record.verify_digest():
            raise AuditStoreError("configuration observation digest is invalid")
        self._verify_parent(record)
        content = canonical_json_bytes(record.model_dump(mode="json"))
        if len(content) > MAX_OBSERVATION_RECORD_BYTES:
            raise AuditStoreError("configuration observation exceeds bounded size")
        self._validate_managed_directory(self._observation_records)
        destination = self._observation_records / f"{record.observation_record_id}.json"
        if destination.exists() or destination.is_symlink():
            raise AuditStoreError("configuration observation identity already exists")
        try:
            self._publish_new(self._observation_records, destination.name, content)
        except FileExistsError:
            raise AuditStoreError(
                "configuration observation identity already exists"
            ) from None
        return destination

    def read_observation_record(
        self, observation_record_id: UUID
    ) -> ConfigurationObservationRecord:
        """Read one canonical observation record and revalidate its parent link."""

        self._validate_root_identity()
        self._validate_managed_directory(self._observation_records)
        destination = self._observation_records / f"{observation_record_id}.json"
        content = self._read_private_file(destination, MAX_OBSERVATION_RECORD_BYTES)
        try:
            record = ConfigurationObservationRecord.model_validate_json(content)
        except ValidationError as error:
            raise AuditStoreError(
                "configuration observation schema is invalid"
            ) from error
        if (
            record.observation_record_id != observation_record_id
            or not record.verify_digest()
        ):
            raise AuditStoreError("configuration observation integrity is invalid")
        if canonical_json_bytes(record.model_dump(mode="json")) != content:
            raise AuditStoreError("configuration observation is not canonical JSON")
        self._verify_parent(record)
        return record

    def iter_observation_records(
        self, *, max_scan: int = MAX_OBSERVATION_RECORD_SCAN
    ) -> tuple[ConfigurationObservationRecord, ...]:
        """Read every observation record deterministically within a hard bound."""

        self._validate_root_identity()
        self._validate_managed_directory(self._observation_records)
        if not 1 <= max_scan <= MAX_OBSERVATION_RECORD_SCAN:
            raise AuditStoreError("configuration observation scan bound is invalid")
        names: list[str] = []
        for entry in os.scandir(self._observation_records):
            if entry.name.startswith(".audit-tmp-"):
                continue
            try:
                record_id = UUID(entry.name.removesuffix(".json"))
            except ValueError:
                raise AuditStoreError(
                    "observation records directory contains an unexpected entry"
                ) from None
            if (
                entry.name != f"{record_id}.json"
                or entry.is_symlink()
                or not entry.is_file(follow_symlinks=False)
            ):
                raise AuditStoreError(
                    "observation records directory contains an unexpected entry"
                )
            names.append(entry.name)
            if len(names) > max_scan:
                raise AuditStoreError("configuration observation scan bound exceeded")
        return tuple(
            self.read_observation_record(UUID(name.removesuffix(".json")))
            for name in sorted(names)
        )

    def find_by_parent(
        self,
        parent_record_id: UUID,
        *,
        max_results: int = MAX_OBSERVATION_QUERY_RESULTS,
        max_scan: int = MAX_OBSERVATION_RECORD_SCAN,
    ) -> tuple[ConfigurationObservationRecord, ...]:
        """Find bounded observations linked to one parent ChangeAuditRecord."""

        self.read_record(parent_record_id)
        return self._find(
            lambda record: record.parent_audit.record_id == parent_record_id,
            max_results=max_results,
            max_scan=max_scan,
        )

    def find_by_device(
        self,
        device_identity: str,
        *,
        max_results: int = MAX_OBSERVATION_QUERY_RESULTS,
        max_scan: int = MAX_OBSERVATION_RECORD_SCAN,
    ) -> tuple[ConfigurationObservationRecord, ...]:
        """Find bounded observations for one exact stable NetBox identity."""

        try:
            validated_identity = _DEVICE_IDENTITY_ADAPTER.validate_python(
                device_identity
            )
        except ValidationError as error:
            raise AuditStoreError(
                "configuration observation device identity is invalid"
            ) from error
        return self._find(
            lambda record: record.target == validated_identity,
            max_results=max_results,
            max_scan=max_scan,
        )

    def _find(
        self,
        predicate: Callable[[ConfigurationObservationRecord], bool],
        *,
        max_results: int,
        max_scan: int,
    ) -> tuple[ConfigurationObservationRecord, ...]:
        if not 1 <= max_results <= MAX_OBSERVATION_QUERY_RESULTS:
            raise AuditStoreError("configuration observation result bound is invalid")
        matches: list[ConfigurationObservationRecord] = []
        for record in self.iter_observation_records(max_scan=max_scan):
            if predicate(record):
                matches.append(record)
                if len(matches) > max_results:
                    raise AuditStoreError(
                        "configuration observation result bound exceeded"
                    )
        return tuple(matches)

    def _verify_parent(self, record: ConfigurationObservationRecord) -> None:
        parent = self.read_record(record.parent_audit.record_id)
        if parent.digest != record.parent_audit.digest:
            raise AuditStoreError("configuration observation parent digest mismatch")
        if record.target not in {target.device for target in parent.targets}:
            raise AuditStoreError("configuration observation target is not in parent")
