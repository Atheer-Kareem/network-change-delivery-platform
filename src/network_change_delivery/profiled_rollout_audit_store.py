"""Optional rollout namespaces with exact source bytes and verified references."""

from uuid import UUID

from network_change_delivery.audit import AuditArtifactKind as Kind
from network_change_delivery.audit import canonical_json_bytes, sha256_identity
from network_change_delivery.audit_store import (
    MAX_AUDIT_ARTIFACT_BYTES,
    AuditStore,
    AuditStoreError,
)
from network_change_delivery.profiled_execution import (
    ProfiledChangeRecord,
    verify_profiled_record_plan,
)
from network_change_delivery.profiled_rollout import read_profiled_rollout
from network_change_delivery.profiled_rollout_audit import (
    ProfiledRolloutAuditRecord,
    ProfiledRolloutChildAuditRecord,
    ProfiledRolloutChronologyRecord,
    child_record_id,
    chronology_record_id,
)
from network_change_delivery.profiled_rollout_authorization import (
    ProfiledRolloutAuthorization,
)
from network_change_delivery.profiled_rollout_final_validation import (
    ProfiledRolloutFinalValidation,
)
from network_change_delivery.profiled_rollout_preflight import ProfiledRolloutPreflight
from network_change_delivery.profiled_rollout_promotion import ProfiledRolloutPromotion

RECORDS = {
    ProfiledRolloutAuditRecord: "rollout-records",
    ProfiledRolloutChildAuditRecord: "rollout-child-records",
    ProfiledRolloutChronologyRecord: "rollout-chronology-records",
}
BLOBS = {
    "parent": read_profiled_rollout,
    "promotion": ProfiledRolloutPromotion.model_validate_json,
    "authorization": ProfiledRolloutAuthorization.model_validate_json,
    "preflight": ProfiledRolloutPreflight.model_validate_json,
    "final": ProfiledRolloutFinalValidation.model_validate_json,
    "execution": ProfiledChangeRecord.model_validate_json,
}


class ProfiledRolloutAuditStore(AuditStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in (*RECORDS.values(), "rollout-artifact-bytes", "rollout-models"):
            path = self.root / name
            if path.exists() or path.is_symlink():
                self._validate_managed_directory(path)

    def prepare_rollout(self, record_id, parent):
        """Structural create-only readiness, not an assurance of future I/O."""
        self._require_writable()
        read_profiled_rollout(parent.model_dump_json().encode())
        identities = {
            ProfiledRolloutAuditRecord: (record_id,),
            ProfiledRolloutChildAuditRecord: tuple(
                child_record_id(record_id, c.device.device_identity)
                for c in parent.children
            ),
            ProfiledRolloutChronologyRecord: tuple(
                chronology_record_id(
                    child_record_id(record_id, c.device.device_identity)
                )
                for c in parent.children
            ),
        }
        for model, ids in identities.items():
            directory = self._managed_directory(self.root / RECORDS[model])
            for identity in ids:
                path = directory / f"{UUID(str(identity))}.json"
                if path.exists() or path.is_symlink():
                    raise AuditStoreError("rollout record identity already exists")
        blobs = self._managed_directory(self.root / "rollout-artifact-bytes")
        models = self._managed_directory(self.root / "rollout-models")
        for name in BLOBS:
            self._managed_directory(blobs / name)
            self._managed_directory(models / name)
        for kind in (
            Kind.PROFILED_DEPLOYMENT_PLAN,
            Kind.PROFILED_COMPLIANCE_RECORD,
            Kind.PROFILED_CHANGE_RECORD,
        ):
            self._managed_directory(self._artifacts / kind.value)
        self._managed_directory(blobs / "child")

    def put_bytes(self, kind, raw):
        self._require_writable()
        if kind != "child" and kind not in BLOBS:
            raise AuditStoreError("unknown rollout artifact")
        if len(raw) > MAX_AUDIT_ARTIFACT_BYTES:
            raise AuditStoreError("rollout artifact exceeds bound")
        if kind in BLOBS and kind != "execution":
            model = BLOBS[kind](raw)
            canonical = canonical_json_bytes(model.model_dump(mode="json"))
            models = self.root / "rollout-models"
            self._validate_managed_directory(models)
            self._validate_managed_directory(models / kind)
            path = models / kind / f"{model.digest[7:]}.json"
            if path.exists() or path.is_symlink():
                if self.find_model(kind, model.digest) != model:
                    raise AuditStoreError("rollout semantic identity collision")
            else:
                self._publish_new(path.parent, path.name, canonical)
        identity = sha256_identity(raw)
        root = self.root / "rollout-artifact-bytes"
        self._validate_managed_directory(root)
        directory = root / kind
        self._validate_managed_directory(directory)
        path = directory / f"{identity[7:]}.json"
        if path.exists() or path.is_symlink():
            if self.read_bytes(kind, identity) != raw:
                raise AuditStoreError("rollout original bytes changed")
        else:
            self._publish_new(directory, path.name, raw)
        if self.read_bytes(kind, identity) != raw:
            raise AuditStoreError("rollout artifact readback failed")
        return identity

    def read_bytes(self, kind, identity):
        self._validate_root_identity()
        from network_change_delivery.profiled_promotion import checked_digest

        checked_digest(identity)
        if kind not in (*BLOBS, "child"):
            raise AuditStoreError("unknown rollout artifact")
        root = self.root / "rollout-artifact-bytes"
        self._validate_managed_directory(root)
        self._validate_managed_directory(root / kind)
        raw = self._read_private_file(
            root / kind / f"{identity[7:]}.json", MAX_AUDIT_ARTIFACT_BYTES
        )
        if sha256_identity(raw) != identity:
            raise AuditStoreError("rollout original byte digest mismatch")
        return raw

    def put_model(self, kind, value):
        return self.put_bytes(kind, canonical_json_bytes(value.model_dump(mode="json")))

    def find_model(self, kind, semantic_digest):
        self._validate_root_identity()
        from network_change_delivery.profiled_promotion import checked_digest

        checked_digest(semantic_digest)
        if kind not in BLOBS or kind == "execution":
            raise AuditStoreError("unknown semantic rollout model")
        root = self.root / "rollout-models" / kind
        self._validate_managed_directory(root.parent)
        self._validate_managed_directory(root)
        raw = self._read_private_file(
            root / f"{semantic_digest[7:]}.json", MAX_AUDIT_ARTIFACT_BYTES
        )
        model = BLOBS[kind](raw)
        if (
            model.digest != semantic_digest
            or canonical_json_bytes(model.model_dump(mode="json")) != raw
        ):
            raise AuditStoreError("rollout semantic artifact mismatch")
        return model

    def persist_rollout_record(self, record):
        self._require_writable()
        model = type(record)
        if model not in RECORDS:
            raise AuditStoreError("unknown rollout record")
        record = model.model_validate(record.model_dump())
        self._verify_references(record)
        directory = self.root / RECORDS[model]
        self._validate_managed_directory(directory)
        raw = canonical_json_bytes(record.model_dump(mode="json"))
        if len(raw) > MAX_AUDIT_ARTIFACT_BYTES:
            raise AuditStoreError("rollout record exceeds bound")
        self._publish_new(directory, f"{record.record_id}.json", raw)
        if self.read_rollout_record(model, record.record_id) != record:
            raise AuditStoreError("rollout record readback rejected")

    def read_rollout_record(self, model, record_id):
        self._validate_root_identity()
        try:
            return self._read_rollout_record(model, record_id)
        except (OSError, ValueError, KeyError, StopIteration) as error:
            raise AuditStoreError("rollout record readback rejected") from error

    def _read_rollout_record(self, model, record_id):
        directory = self.root / RECORDS[model]
        self._validate_managed_directory(directory)
        raw = self._read_private_file(
            directory / f"{UUID(str(record_id))}.json", MAX_AUDIT_ARTIFACT_BYTES
        )
        record = model.model_validate_json(raw)
        if (
            record.record_id != record_id
            or canonical_json_bytes(record.model_dump(mode="json")) != raw
        ):
            raise AuditStoreError("rollout record identity/bytes rejected")
        self._verify_references(record)
        return record

    def _verify_references(self, record):
        if isinstance(record, ProfiledRolloutChronologyRecord):
            child = self.read_rollout_record(
                ProfiledRolloutChildAuditRecord, record.child_audit.record_id
            )
            if (
                child.digest != record.child_audit.digest
                or child.child.device_identity != record.device_identity
                or not child.execution_attempted
                or child.pre_status != record.pre.status.value
                or child.post_status != record.post.status.value
            ):
                raise AuditStoreError("rollout chronology child mismatch")
            return
        parent = self.find_model("parent", record.parent_digest)
        auth = self.find_model("authorization", record.authorization_digest)
        promotion = self.find_model("promotion", record.promotion_digest)
        if (
            auth.parent_digest != parent.digest
            or auth.promotion_digest != promotion.digest
            or record.build_id != UUID(auth.build_id)
            or record.source_commit != auth.source_commit
            or auth.selected_devices
            != tuple(c.device.device_identity for c in parent.children)
            or promotion.parent_digest != parent.digest
        ):
            raise AuditStoreError("rollout authority references mismatch")
        if record.preflight_digest:
            preflight = self.find_model("preflight", record.preflight_digest)
            if (
                preflight.parent_digest != parent.digest
                or preflight.authorization_digest != auth.digest
            ):
                raise AuditStoreError("rollout preflight mismatch")
        if isinstance(record, ProfiledRolloutChildAuditRecord):
            approved = next(
                c
                for c in parent.children
                if c.device.device_identity == record.child.device_identity
            )
            self._verify_binding(approved, record.child)
            cohorts = [(d, "CANARY", 0) for d in parent.canaries] + [
                (d, "WAVE", i) for i, wave in enumerate(parent.waves) for d in wave
            ]
            if record.execution_order >= len(cohorts) or cohorts[
                record.execution_order
            ] != (
                record.child.device_identity,
                record.cohort_kind,
                record.cohort_index,
            ):
                raise AuditStoreError("rollout child cohort mismatch")
            raw = self.read_bytes("child", record.child.artifact_digest)
            if raw != approved.artifact_bytes():
                raise AuditStoreError("rollout child original bytes mismatch")
            if record.execution_digest:
                execution = ProfiledChangeRecord.model_validate_json(
                    self.read_bytes("execution", record.execution_digest)
                )
                verify_profiled_record_plan(execution, approved.result())
                if execution.final_outcome != record.final_outcome:
                    raise AuditStoreError("rollout execution outcome mismatch")
            return
        if (
            record.parent_artifact_digest != auth.parent_artifact_digest
            or record.promotion_artifact_digest != auth.promotion_artifact_digest
            or UUID(auth.unblocker_id) != record.unblocker_id
            or record.canaries != parent.canaries
            or record.waves != parent.waves
            or len(record.children) != len(parent.children)
        ):
            raise AuditStoreError("rollout frozen parent mismatch")
        self.read_bytes("parent", record.parent_artifact_digest)
        self.read_bytes("promotion", record.promotion_artifact_digest)
        for approved, child in zip(parent.children, record.children, strict=True):
            self._verify_binding(approved, child)
        records = []
        for ref in record.child_records:
            child = self.read_rollout_record(
                ProfiledRolloutChildAuditRecord, ref.record_id
            )
            if child.digest != ref.digest or child.parent_record_id != record.record_id:
                raise AuditStoreError("rollout child record reference mismatch")
            records.append(child)
        chronology_children = []
        for ref in record.chronology_records:
            chronology = self.read_rollout_record(
                ProfiledRolloutChronologyRecord, ref.record_id
            )
            if (
                chronology.digest != ref.digest
                or chronology.child_audit.record_id
                not in {c.record_id for c in records}
            ):
                raise AuditStoreError("rollout chronology reference mismatch")
            chronology_children.append(chronology.child_audit.record_id)
            if (
                record.outcome == "SUCCEEDED"
                and chronology.overall_status != "SUCCEEDED"
            ):
                raise AuditStoreError("rollout success chronology incomplete")
        if record.final_validation_digest:
            final = self.find_model("final", record.final_validation_digest)
            if (
                final.status != record.final_validation_status
                or final.parent_digest != parent.digest
                or final.authorization_digest != auth.digest
                or final.preflight_digest != record.preflight_digest
                or final.selected_devices != auth.selected_devices
            ):
                raise AuditStoreError("rollout final validation mismatch")
        if record.outcome == "SUCCEEDED" and (
            tuple(c.child.device_identity for c in records if c.execution_attempted)
            != record.attempted
            or any(c.final_outcome != "SUCCEEDED" for c in records)
            or len(set(chronology_children)) != len(record.attempted)
        ):
            raise AuditStoreError("rollout success evidence incomplete")

    @staticmethod
    def _verify_binding(approved, binding):
        if (
            approved.device.device_identity != binding.device_identity
            or approved.interface.interface != binding.interface_identity
            or approved.kind != binding.kind
            or approved.artifact_digest != binding.artifact_digest
            or approved.result_digest != binding.result_digest
        ):
            raise AuditStoreError("rollout approved child mismatch")

    def iter_rollout_records(self, *, limit=50):
        self._validate_root_identity()
        directory = self.root / RECORDS[ProfiledRolloutAuditRecord]
        if not directory.exists() and not directory.is_symlink():
            return ()
        self._validate_managed_directory(directory)
        return tuple(
            self.read_rollout_record(ProfiledRolloutAuditRecord, UUID(path.stem))
            for path in sorted(directory.glob("*.json"))[:limit]
        )
