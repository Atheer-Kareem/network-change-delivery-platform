"""Separate current chronology namespace over the existing AuditStore root."""

import os
from uuid import UUID

from network_change_delivery.audit import AuditArtifactKind as Kind
from network_change_delivery.audit import canonical_json_bytes
from network_change_delivery.audit_store import AuditStore, AuditStoreError
from network_change_delivery.profiled_audit import ProfiledDeliveryKind
from network_change_delivery.profiled_configuration_observation import (
    ProfiledConfigurationObservationRecord,
    chronology_id,
)

MAX_RECORD_BYTES = 64 * 1024
MAX_SCAN = 10_000


class ProfiledConfigurationObservationStore(AuditStore):
    @property
    def _profiled_observations(self):
        return self.root / "profiled-observation-records"

    def prepare_profiled_observation_publication(self, parent_id: UUID):
        self._require_writable()
        self._validate_root_identity()
        directory = self._managed_directory(self._profiled_observations)
        path = directory / f"{chronology_id(parent_id)}.json"
        if path.exists() or path.is_symlink():
            raise AuditStoreError("profiled chronology child already exists")

    def _verify_profiled_parent(self, child):
        parent = self.read_profiled_record(child.parent_audit.record_id)
        if (
            parent.digest != child.parent_audit.digest
            or parent.delivery_kind is not ProfiledDeliveryKind.EXECUTION
            or parent.target.device != child.target
            or {ref.kind for ref in parent.artifacts}
            != {
                Kind.PROFILED_DEPLOYMENT_PLAN,
                Kind.PROFILED_PROMOTION,
                Kind.PROFILED_CHANGE_RECORD,
            }
        ):
            raise AuditStoreError("profiled chronology parent rejected")

    def persist_profiled_observation_record(self, record):
        self._require_writable()
        record = ProfiledConfigurationObservationRecord.model_validate(
            record.model_dump()
        )
        self._verify_profiled_parent(record)
        content = canonical_json_bytes(record.model_dump(mode="json"))
        if len(content) > MAX_RECORD_BYTES:
            raise AuditStoreError("profiled chronology size rejected")
        self.prepare_profiled_observation_publication(record.parent_audit.record_id)
        destination = (
            self._profiled_observations / f"{record.observation_record_id}.json"
        )
        try:
            self._publish_new(destination.parent, destination.name, content)
        except FileExistsError:
            raise AuditStoreError("profiled chronology child already exists") from None
        return destination

    def read_profiled_observation_record(self, record_id):
        self._validate_root_identity()
        self._validate_managed_directory(self._profiled_observations)
        record_id = UUID(str(record_id))
        content = self._read_private_file(
            self._profiled_observations / f"{record_id}.json", MAX_RECORD_BYTES
        )
        try:
            record = ProfiledConfigurationObservationRecord.model_validate_json(content)
        except ValueError:
            raise AuditStoreError(
                "profiled chronology schema/digest rejected"
            ) from None
        if (
            record.observation_record_id != record_id
            or canonical_json_bytes(record.model_dump(mode="json")) != content
        ):
            raise AuditStoreError("profiled chronology identity/bytes rejected")
        self._verify_profiled_parent(record)
        return record

    def iter_profiled_observation_records(self, *, max_scan=MAX_SCAN):
        self._validate_root_identity()
        if not 1 <= max_scan <= MAX_SCAN:
            raise AuditStoreError("profiled chronology scan bound rejected")
        directory = self._profiled_observations
        if not directory.exists() and not directory.is_symlink():
            return ()
        self._validate_managed_directory(directory)
        names = []
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name.startswith(".audit-tmp-"):
                    continue
                try:
                    identity = UUID(entry.name.removesuffix(".json"))
                except ValueError:
                    raise AuditStoreError(
                        "profiled chronology entry rejected"
                    ) from None
                if (
                    entry.name != f"{identity}.json"
                    or entry.is_symlink()
                    or not entry.is_file(follow_symlinks=False)
                ):
                    raise AuditStoreError("profiled chronology entry rejected")
                names.append(entry.name)
                if len(names) > max_scan:
                    raise AuditStoreError("profiled chronology scan bound exceeded")
        return tuple(
            self.read_profiled_observation_record(UUID(n[:-5])) for n in sorted(names)
        )

    def find_by_profiled_parent(self, parent_record_id):
        parent = self.read_profiled_record(UUID(str(parent_record_id)))
        if parent.delivery_kind is not ProfiledDeliveryKind.EXECUTION:
            return ()
        # One deterministic child; no unbounded scan or ambiguous schema lookup.
        self._validate_root_identity()
        if (
            not self._profiled_observations.exists()
            and not self._profiled_observations.is_symlink()
        ):
            return ()
        self._validate_managed_directory(self._profiled_observations)
        identity = chronology_id(parent.record_id)
        path = self._profiled_observations / f"{identity}.json"
        if not path.exists() and not path.is_symlink():
            return ()
        return (self.read_profiled_observation_record(identity),)
