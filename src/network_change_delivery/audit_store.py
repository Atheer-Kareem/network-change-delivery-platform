"""Private append-only filesystem persistence for bounded audit evidence."""

from __future__ import annotations

import errno
import json
import os
import stat
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import fields
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, TypeAdapter, ValidationError

from network_change_delivery.audit import (
    AuditArtifactKind,
    AuditArtifactReference,
    ChangeAuditRecord,
    canonical_json_bytes,
    sha256_identity,
)
from network_change_delivery.ephemeral_staging import StagingEvidence
from network_change_delivery.models import (
    ChangeRecord,
    DeploymentPlan,
    FleetChangeRecord,
    FleetDeploymentPlan,
)
from network_change_delivery.plan_assurance import PlanAssuranceRecord
from network_change_delivery.profiled_audit import (
    ProfiledDeliveryAuditRecord,
    verify_profiled_audit_artifacts,
)
from network_change_delivery.profiled_execution import ProfiledChangeRecord
from network_change_delivery.profiled_planning import (
    ProfiledComplianceRecord,
    ProfiledDeploymentPlan,
)
from network_change_delivery.profiled_promotion import ProfiledPromotion
from network_change_delivery.promotion import DeploymentPromotionManifest
from network_change_delivery.snmp_provisioning import (
    SnmpProvisioningPlan,
    SnmpProvisioningRecord,
)

MAX_AUDIT_RECORD_BYTES = 256 * 1024
MAX_AUDIT_ARTIFACT_BYTES = 4 * 1024 * 1024
MAX_AUDIT_RECORD_SCAN = 10_000

type AuditArtifact = (
    DeploymentPlan
    | FleetDeploymentPlan
    | PlanAssuranceRecord
    | DeploymentPromotionManifest
    | StagingEvidence
    | ChangeRecord
    | FleetChangeRecord
    | SnmpProvisioningPlan
    | SnmpProvisioningRecord
    | ProfiledDeploymentPlan
    | ProfiledComplianceRecord
    | ProfiledPromotion
    | ProfiledChangeRecord
)

_ARTIFACT_TYPES: dict[AuditArtifactKind, type[object]] = {
    AuditArtifactKind.DEPLOYMENT_PLAN: DeploymentPlan,
    AuditArtifactKind.FLEET_DEPLOYMENT_PLAN: FleetDeploymentPlan,
    AuditArtifactKind.SNMP_PROVISIONING_PLAN: SnmpProvisioningPlan,
    AuditArtifactKind.PLAN_ASSURANCE_RECORD: PlanAssuranceRecord,
    AuditArtifactKind.DEPLOYMENT_PROMOTION_MANIFEST: DeploymentPromotionManifest,
    AuditArtifactKind.STAGING_EVIDENCE: StagingEvidence,
    AuditArtifactKind.CHANGE_RECORD: ChangeRecord,
    AuditArtifactKind.FLEET_CHANGE_RECORD: FleetChangeRecord,
    AuditArtifactKind.SNMP_PROVISIONING_RECORD: SnmpProvisioningRecord,
}
_PROFILED_ARTIFACT_TYPES = {
    AuditArtifactKind.PROFILED_DEPLOYMENT_PLAN: ProfiledDeploymentPlan,
    AuditArtifactKind.PROFILED_COMPLIANCE_RECORD: ProfiledComplianceRecord,
    AuditArtifactKind.PROFILED_PROMOTION: ProfiledPromotion,
    AuditArtifactKind.PROFILED_CHANGE_RECORD: ProfiledChangeRecord,
}
_ARTIFACT_TYPES.update(_PROFILED_ARTIFACT_TYPES)

_INTRINSIC_DIGEST_KINDS = {
    AuditArtifactKind.PROFILED_DEPLOYMENT_PLAN,
    AuditArtifactKind.PROFILED_COMPLIANCE_RECORD,
    AuditArtifactKind.PROFILED_PROMOTION,
    AuditArtifactKind.DEPLOYMENT_PLAN,
    AuditArtifactKind.FLEET_DEPLOYMENT_PLAN,
    AuditArtifactKind.SNMP_PROVISIONING_PLAN,
    AuditArtifactKind.PLAN_ASSURANCE_RECORD,
    AuditArtifactKind.DEPLOYMENT_PROMOTION_MANIFEST,
}
_STAGING_FIELDS = frozenset(item.name for item in fields(StagingEvidence))
_STAGING_ADAPTER = TypeAdapter(StagingEvidence)


class AuditStoreError(ValueError):
    """Bounded fail-closed audit persistence error."""


class AuditStore:
    """Append-only content-addressed artifact and audit-record store."""

    def __init__(self, root: Path, *, checkout: Path, create: bool = True) -> None:
        self.root = self._validate_root(root, checkout)
        self._create = create
        self._uid = os.getuid()
        metadata = self.root.stat(follow_symlinks=False)
        self._root_identity = (metadata.st_dev, metadata.st_ino)
        self._artifacts = self._managed_directory(self.root / "artifacts")
        self._records = self._managed_directory(self.root / "records")
        # Optional namespaces: opening a historical store never creates/migrates them.
        self._profiled_records = self.root / "profiled-records"
        self._profiled_bytes = self.root / "profiled-artifact-bytes"
        for path in (self._profiled_records, self._profiled_bytes):
            if path.exists() or path.is_symlink():
                self._validate_managed_directory(path)

    def persist_artifact(
        self, kind: AuditArtifactKind, artifact: AuditArtifact
    ) -> AuditArtifactReference:
        """Durably publish or safely reuse one approved immutable artifact."""
        self._require_writable()
        self._validate_root_identity()
        try:
            kind = AuditArtifactKind(kind)
        except ValueError:
            raise AuditStoreError("audit artifact kind is unsupported") from None
        validated, content, identity, schema_version = self._prepare_artifact(
            kind, artifact
        )
        del validated
        if len(content) > MAX_AUDIT_ARTIFACT_BYTES:
            raise AuditStoreError("audit artifact exceeds bounded size")
        self._validate_managed_directory(self._artifacts)
        directory = self._managed_directory(self._artifacts / kind.value)
        reference = AuditArtifactReference(
            kind=kind,
            schema_version=schema_version,
            sha256=identity,
            locator=f"artifacts/{kind.value}/{identity[7:]}.json",
            size_bytes=len(content),
        )
        destination = self.root / reference.locator
        if destination.exists() or destination.is_symlink():
            self.read_artifact(reference)
            return reference
        try:
            self._publish_new(directory, destination.name, content)
        except FileExistsError:
            self.read_artifact(reference)
        return reference

    def read_artifact(self, reference: AuditArtifactReference) -> AuditArtifact:
        """Read and fully validate exactly one referenced artifact."""
        self._validate_root_identity()
        reference = AuditArtifactReference.model_validate(reference)
        expected = self.root / reference.locator
        self._validate_artifact_parent(reference, expected.parent)
        content = self._read_private_file(expected, MAX_AUDIT_ARTIFACT_BYTES)
        if len(content) != reference.size_bytes:
            raise AuditStoreError("audit artifact size does not match reference")
        artifact = self._decode_artifact(reference.kind, content)
        _, canonical, identity, schema_version = self._prepare_artifact(
            reference.kind, artifact
        )
        if canonical != content:
            raise AuditStoreError("audit artifact is not canonical JSON")
        if identity != reference.sha256 or schema_version != reference.schema_version:
            raise AuditStoreError("audit artifact integrity does not match reference")
        return artifact

    def persist_record(self, record: ChangeAuditRecord) -> Path:
        """Publish a record only after every referenced artifact verifies."""
        self._require_writable()
        self._validate_root_identity()
        record = ChangeAuditRecord.model_validate(
            record.model_dump(mode="json", warnings=False)
        )
        if not record.verify_digest():
            raise AuditStoreError("audit record digest is invalid")
        content = canonical_json_bytes(record.model_dump(mode="json"))
        if len(content) > MAX_AUDIT_RECORD_BYTES:
            raise AuditStoreError("audit record exceeds bounded size")
        for reference in record.artifacts:
            self.read_artifact(reference)
        self._validate_managed_directory(self._records)
        destination = self._records / f"{record.record_id}.json"
        if destination.exists() or destination.is_symlink():
            raise AuditStoreError("audit record identity already exists")
        try:
            self._publish_new(self._records, destination.name, content)
        except FileExistsError:
            raise AuditStoreError("audit record identity already exists") from None
        return destination

    def read_record(self, record_id: UUID) -> ChangeAuditRecord:
        """Read one directly addressed record after schema and digest validation."""
        self._validate_root_identity()
        self._validate_managed_directory(self._records)
        destination = self._records / f"{record_id}.json"
        content = self._read_private_file(destination, MAX_AUDIT_RECORD_BYTES)
        try:
            record = ChangeAuditRecord.model_validate_json(content)
        except ValidationError as error:
            raise AuditStoreError("audit record schema is invalid") from error
        if record.record_id != record_id or not record.verify_digest():
            raise AuditStoreError("audit record integrity is invalid")
        if canonical_json_bytes(record.model_dump(mode="json")) != content:
            raise AuditStoreError("audit record is not canonical JSON")
        for reference in record.artifacts:
            self.read_artifact(reference)
        return record

    def iter_records(
        self, *, max_scan: int = MAX_AUDIT_RECORD_SCAN
    ) -> tuple[ChangeAuditRecord, ...]:
        """Read every durable record in deterministic order within a hard bound."""
        self._validate_root_identity()
        self._validate_managed_directory(self._records)
        if not 1 <= max_scan <= MAX_AUDIT_RECORD_SCAN:
            raise AuditStoreError("audit record scan bound is invalid")
        names: list[str] = []
        for entry in os.scandir(self._records):
            if entry.name.startswith(".audit-tmp-"):
                continue
            try:
                record_id = UUID(entry.name.removesuffix(".json"))
            except ValueError:
                raise AuditStoreError(
                    "audit records directory contains an unexpected entry"
                ) from None
            if (
                entry.name != f"{record_id}.json"
                or entry.is_symlink()
                or not entry.is_file(follow_symlinks=False)
            ):
                raise AuditStoreError(
                    "audit records directory contains an unexpected entry"
                )
            names.append(entry.name)
            if len(names) > max_scan:
                raise AuditStoreError("audit record scan bound exceeded")
        return tuple(
            self.read_record(UUID(name.removesuffix(".json"))) for name in sorted(names)
        )

    def prepare_profiled_publication(
        self, record_id: UUID, kinds: frozenset[AuditArtifactKind]
    ) -> None:
        """Admit managed destinations before a possible write; publish no record.

        This is structural readiness, not a reservation or a promise that later
        I/O cannot fail. Immutable partial inputs are intentionally retained.
        """
        self._require_writable()
        self._validate_root_identity()
        execution = frozenset(
            {
                AuditArtifactKind.PROFILED_DEPLOYMENT_PLAN,
                AuditArtifactKind.PROFILED_PROMOTION,
                AuditArtifactKind.PROFILED_CHANGE_RECORD,
            }
        )
        compliance = frozenset({AuditArtifactKind.PROFILED_COMPLIANCE_RECORD})
        if kinds not in (execution, compliance) or not isinstance(record_id, UUID):
            raise AuditStoreError("profiled preparation scope rejected")
        directory = self._managed_directory(self._profiled_records)
        destination = directory / f"{record_id}.json"
        if destination.exists() or destination.is_symlink():
            raise AuditStoreError("profiled audit record identity already exists")
        raw_root = self._managed_directory(self._profiled_bytes)
        self._validate_managed_directory(self._artifacts)
        for kind in sorted(kinds, key=str):
            self._managed_directory(raw_root / kind.value)
            self._managed_directory(self._artifacts / kind.value)

    def persist_profiled_record(
        self,
        record: ProfiledDeliveryAuditRecord,
        *,
        artifact_bytes: Mapping[AuditArtifactKind, bytes],
    ) -> Path:
        """Validate artifacts and original bytes before envelope publication.

        Canonical artifacts must already be persisted. Source bytes are retained
        separately so later readers can verify their hashes without reformatting.
        Interrupted publication may leave immutable artifacts but no final envelope.
        """
        self._require_writable()
        self._validate_root_identity()
        record = self._validate_profiled_record(record)
        artifact_bytes = dict(artifact_bytes)
        content = canonical_json_bytes(record.model_dump(mode="json"))
        if len(content) > MAX_AUDIT_RECORD_BYTES:
            raise AuditStoreError("profiled audit record exceeds bounded size")
        self._verify_profiled_references(record, artifact_bytes)
        directory = self._managed_directory(self._profiled_records)
        destination = directory / f"{record.record_id}.json"
        if destination.exists() or destination.is_symlink():
            raise AuditStoreError("profiled audit record identity already exists")
        raw_root = self._managed_directory(self._profiled_bytes)
        for kind, digest in record.byte_digests_by_kind().items():
            parent = self._managed_directory(raw_root / kind.value)
            raw_path = parent / f"{digest[7:]}.json"
            raw = artifact_bytes[kind]
            if raw_path.exists() or raw_path.is_symlink():
                if self._read_private_file(raw_path, MAX_AUDIT_ARTIFACT_BYTES) != raw:
                    raise AuditStoreError("profiled artifact bytes conflict")
            else:
                try:
                    self._publish_new(parent, raw_path.name, raw)
                except FileExistsError:
                    if (
                        self._read_private_file(raw_path, MAX_AUDIT_ARTIFACT_BYTES)
                        != raw
                    ):
                        raise AuditStoreError(
                            "profiled artifact bytes conflict"
                        ) from None
        try:
            self._publish_new(directory, destination.name, content)
        except FileExistsError:
            raise AuditStoreError(
                "profiled audit record identity already exists"
            ) from None
        return destination

    @staticmethod
    def _validate_profiled_record(
        record: ProfiledDeliveryAuditRecord,
    ) -> ProfiledDeliveryAuditRecord:
        try:
            return ProfiledDeliveryAuditRecord.model_validate(
                record.model_dump(mode="json", warnings=False)
            )
        except (ValueError, AttributeError) as error:
            raise AuditStoreError(
                "profiled audit record schema/digest invalid"
            ) from error

    def _verify_profiled_references(
        self,
        record: ProfiledDeliveryAuditRecord,
        artifact_bytes: Mapping[AuditArtifactKind, bytes],
    ) -> None:
        digests = record.byte_digests_by_kind()
        if set(artifact_bytes) != set(digests):
            raise AuditStoreError("profiled artifact byte set rejected")
        artifacts = {}
        for ref in record.artifacts:
            artifact = self.read_artifact(ref)
            raw = artifact_bytes[ref.kind]
            if (
                not isinstance(raw, bytes)
                or not 0 < len(raw) <= MAX_AUDIT_ARTIFACT_BYTES
            ):
                raise AuditStoreError("profiled source artifact bytes exceed bound")
            if sha256_identity(raw) != digests[ref.kind]:
                raise AuditStoreError("profiled source artifact byte digest rejected")
            decoded = self._decode_artifact(ref.kind, raw)
            if canonical_json_bytes(
                decoded.model_dump(mode="json")
            ) != canonical_json_bytes(artifact.model_dump(mode="json")):
                raise AuditStoreError(
                    "profiled source bytes differ from canonical artifact"
                )
            artifacts[ref.kind] = artifact
        try:
            verify_profiled_audit_artifacts(record, artifacts)
        except ValueError as error:
            raise AuditStoreError(
                "profiled cross-artifact correlation rejected"
            ) from error

    def read_profiled_record(self, record_id: UUID) -> ProfiledDeliveryAuditRecord:
        """Read a current envelope and validate canonical and original-byte evidence."""
        self._validate_root_identity()
        self._validate_managed_directory(self._profiled_records)
        try:
            record_id = UUID(str(record_id))
        except ValueError:
            raise AuditStoreError("profiled audit record ID invalid") from None
        content = self._read_private_file(
            self._profiled_records / f"{record_id}.json", MAX_AUDIT_RECORD_BYTES
        )
        try:
            record = ProfiledDeliveryAuditRecord.model_validate_json(content)
        except ValueError as error:
            raise AuditStoreError(
                "profiled audit record schema/digest invalid"
            ) from error
        if (
            record.record_id != record_id
            or canonical_json_bytes(record.model_dump(mode="json")) != content
        ):
            raise AuditStoreError(
                "profiled audit record identity/canonical bytes invalid"
            )
        self._validate_managed_directory(self._profiled_bytes)
        raw = {}
        for kind, digest in record.byte_digests_by_kind().items():
            parent = self._profiled_bytes / kind.value
            self._validate_managed_directory(parent)
            raw[kind] = self._read_private_file(
                parent / f"{digest[7:]}.json", MAX_AUDIT_ARTIFACT_BYTES
            )
        self._verify_profiled_references(record, raw)
        return record

    def iter_profiled_records(
        self, *, max_scan: int = MAX_AUDIT_RECORD_SCAN
    ) -> tuple[ProfiledDeliveryAuditRecord, ...]:
        """Bounded deterministic current-only scan; old stores need no migration."""
        self._validate_root_identity()
        if not 1 <= max_scan <= MAX_AUDIT_RECORD_SCAN:
            raise AuditStoreError("profiled audit scan bound invalid")
        if (
            not self._profiled_records.exists()
            and not self._profiled_records.is_symlink()
        ):
            return ()
        self._validate_managed_directory(self._profiled_records)
        names = []
        with os.scandir(self._profiled_records) as entries:
            for entry in entries:
                if entry.name.startswith(".audit-tmp-"):
                    continue
                try:
                    record_id = UUID(entry.name.removesuffix(".json"))
                except ValueError:
                    raise AuditStoreError(
                        "profiled audit directory entry invalid"
                    ) from None
                if (
                    entry.name != f"{record_id}.json"
                    or entry.is_symlink()
                    or not entry.is_file(follow_symlinks=False)
                ):
                    raise AuditStoreError("profiled audit directory entry invalid")
                names.append(entry.name)
                if len(names) > max_scan:
                    raise AuditStoreError("profiled audit scan bound exceeded")
        return tuple(
            self.read_profiled_record(UUID(name[:-5])) for name in sorted(names)
        )

    @staticmethod
    def _validate_root(root: Path, checkout: Path) -> Path:
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise AuditStoreError("audit store root is invalid")
        if not checkout.is_absolute() or not checkout.is_dir():
            raise AuditStoreError("audit checkout context is invalid")
        resolved = root.resolve(strict=True)
        checkout_resolved = checkout.resolve(strict=True)
        if resolved == checkout_resolved or resolved.is_relative_to(checkout_resolved):
            raise AuditStoreError("audit store root must be outside checkout")
        metadata = root.stat(follow_symlinks=False)
        if metadata.st_uid != os.getuid():
            raise AuditStoreError("audit store root owner is invalid")
        mode = stat.S_IMODE(metadata.st_mode)
        if mode != 0o700:
            raise AuditStoreError("audit store root permissions are invalid")
        return resolved

    def _validate_root_identity(self) -> None:
        if self.root.is_symlink() or not self.root.is_dir():
            raise AuditStoreError("audit store root changed")
        metadata = self.root.stat(follow_symlinks=False)
        if (
            metadata.st_uid != self._uid
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or (metadata.st_dev, metadata.st_ino) != self._root_identity
        ):
            raise AuditStoreError("audit store root changed")

    def _require_writable(self) -> None:
        if not self._create:
            raise AuditStoreError("audit store is read-only")

    def _managed_directory(self, path: Path) -> Path:
        if hasattr(self, "_root_identity"):
            self._validate_root_identity()
        if self._create:
            with suppress(FileExistsError):
                path.mkdir(mode=0o700)
        self._validate_managed_directory(path)
        return path

    def _validate_managed_directory(self, path: Path) -> None:
        if path.is_symlink() or not path.is_dir():
            raise AuditStoreError("audit managed directory is invalid")
        try:
            path.resolve(strict=True).relative_to(self.root)
        except ValueError:
            raise AuditStoreError("audit managed directory escapes root") from None
        metadata = path.stat(follow_symlinks=False)
        if metadata.st_uid != self._uid or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise AuditStoreError("audit managed directory permissions are invalid")

    def _validate_artifact_parent(
        self, reference: AuditArtifactReference, parent: Path
    ) -> None:
        expected = self._artifacts / reference.kind.value
        if parent != expected:
            raise AuditStoreError("audit artifact locator escapes kind directory")
        self._validate_managed_directory(self._artifacts)
        self._validate_managed_directory(parent)

    def _prepare_artifact(
        self, kind: AuditArtifactKind, artifact: AuditArtifact
    ) -> tuple[AuditArtifact, bytes, str, str]:
        expected_type = _ARTIFACT_TYPES[kind]
        if not isinstance(artifact, expected_type):
            raise AuditStoreError("audit artifact kind and schema disagree")
        if kind in _PROFILED_ARTIFACT_TYPES:
            artifact = self._decode_artifact(
                kind,
                canonical_json_bytes(artifact.model_dump(mode="json", warnings=False)),
            )
        if isinstance(artifact, StagingEvidence):
            payload = artifact.safe_dict()
            validated = self._validate_staging_payload(payload)
            content = canonical_json_bytes(validated.safe_dict())
        else:
            validated = artifact
            content = canonical_json_bytes(validated.model_dump(mode="json"))
        schema_version = str(validated.schema_version)
        if kind in _INTRINSIC_DIGEST_KINDS:
            digest_valid = (
                validated.digest == validated.calculated_digest()
                if kind in _PROFILED_ARTIFACT_TYPES
                else isinstance(validated, BaseModel) and validated.verify_digest()
            )
            if not digest_valid:
                raise AuditStoreError("intrinsic audit artifact digest is invalid")
            identity = str(validated.digest)
        else:
            identity = sha256_identity(content)
        return validated, content, identity, schema_version

    @staticmethod
    def _validate_staging_payload(payload: object) -> StagingEvidence:
        if not isinstance(payload, dict) or set(payload) != _STAGING_FIELDS:
            raise AuditStoreError("staging evidence schema is invalid")
        try:
            evidence = _STAGING_ADAPTER.validate_python(payload)
        except ValidationError as error:
            raise AuditStoreError("staging evidence schema is invalid") from error
        if evidence.schema_version not in {"1", "2"}:
            raise AuditStoreError("staging evidence schema version is unsupported")
        return evidence

    @staticmethod
    def _unique_profiled_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value = {}
        for key, item in pairs:
            if key in value:
                raise AuditStoreError("duplicate profiled artifact field")
            value[key] = item
        return value

    def _decode_artifact(
        self, kind: AuditArtifactKind, content: bytes
    ) -> AuditArtifact:
        try:
            payload = json.loads(
                content,
                object_pairs_hook=(
                    self._unique_profiled_fields
                    if kind in _PROFILED_ARTIFACT_TYPES
                    else None
                ),
            )
            if kind is AuditArtifactKind.STAGING_EVIDENCE:
                return self._validate_staging_payload(payload)
            model = _ARTIFACT_TYPES[kind]
            if not issubclass(model, BaseModel):
                raise AuditStoreError("audit artifact schema is unsupported")
            return model.model_validate(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as error:
            raise AuditStoreError("audit artifact schema is invalid") from error

    def _read_private_file(self, path: Path, limit: int) -> bytes:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as error:
            raise AuditStoreError("audit file is missing or unsafe") from error
        try:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != self._uid
                or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_size > limit
            ):
                raise AuditStoreError("audit file metadata is invalid")
            chunks: list[bytes] = []
            remaining = before.st_size
            while remaining:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    raise AuditStoreError("audit file changed during read")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise AuditStoreError("audit file exceeds bounded size")
            after = os.fstat(descriptor)
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise AuditStoreError("audit file changed during read")
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    @staticmethod
    def _publish_new(directory: Path, final_name: str, content: bytes) -> None:
        """Publish via hard link; link fails with EEXIST and never replaces."""
        directory_flags = (
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            directory_descriptor = os.open(directory, directory_flags)
        except OSError as error:
            raise AuditStoreError("audit publication directory is unsafe") from error
        temporary_name = f".audit-tmp-{uuid4()}"
        file_descriptor: int | None = None
        linked = False
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            file_descriptor = os.open(
                temporary_name, flags, 0o600, dir_fd=directory_descriptor
            )
            view = memoryview(content)
            while view:
                written = os.write(file_descriptor, view)
                if written <= 0:
                    raise AuditStoreError("audit write did not complete")
                view = view[written:]
            os.fsync(file_descriptor)
            os.close(file_descriptor)
            file_descriptor = None
            os.link(
                temporary_name,
                final_name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            linked = True
            os.fsync(directory_descriptor)
        except OSError as error:
            if linked:
                with suppress(OSError):
                    os.unlink(final_name, dir_fd=directory_descriptor)
                    os.fsync(directory_descriptor)
                linked = False
            if error.errno == errno.EEXIST:
                raise FileExistsError(final_name) from None
            raise AuditStoreError("audit file publication failed") from error
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)
            with suppress(OSError):
                os.unlink(temporary_name, dir_fd=directory_descriptor)
                if linked:
                    os.fsync(directory_descriptor)
            os.close(directory_descriptor)
