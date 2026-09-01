"""Append-only durable acceptance and D0 comparison contracts.

The store has no default location.  Callers must explicitly supply a private
root outside the checkout; B5-1 therefore cannot initialize operator state as a
side effect of importing or testing this module.
"""

from __future__ import annotations

import errno
import os
import re
import stat
from contextlib import suppress
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from network_change_delivery.architecture_contracts import (
    AcceptanceEvidenceReference,
    AcceptedManagedStateRef,
    GitCommit,
    ManagedOwnershipEnvelope,
    ManagedVertical,
    Sha256Digest,
)
from network_change_delivery.audit import canonical_json_bytes, sha256_identity
from network_change_delivery.managed_state import (
    MANAGED_STATE_ADAPTER,
    ManagedStateSnapshot,
)

MAX_MANAGED_STATE_RECORD_BYTES = 256 * 1024
MAX_MANAGED_STATE_RECORD_SCAN = 1_024
_RECORD_NAME = re.compile(r"^(?P<digest>[0-9a-f]{64})\.json$")


class ManagedStateStoreError(ValueError):
    """Managed state is unsafe, corrupt, ambiguous, or outside its bounds."""


def _validate_state(state: ManagedStateSnapshot) -> ManagedStateSnapshot:
    if isinstance(state, BaseModel):
        state = state.model_dump(mode="json")
    return MANAGED_STATE_ADAPTER.validate_python(state)


class ManagedStateAcceptanceMode(StrEnum):
    INITIAL_ADOPTION = "initial_adoption"
    POST_WRITE_VALIDATED = "post_write_validated"


class D0ObservationOutcome(StrEnum):
    IN_SYNC = "in_sync"
    DRIFT_DETECTED = "drift_detected"


class D0ProposalOutcome(StrEnum):
    NO_CHANGE = "no_change"
    CHANGE_PROPOSED = "change_proposed"


class PostWriteOutcome(StrEnum):
    CONVERGED = "converged"
    POST_VALIDATION_FAILED = "post_validation_failed"


class ManagedStateComparison(BaseModel):
    """Pure comparison evidence bound to one exact managed-state subject."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    vertical: ManagedVertical
    ownership_envelope: ManagedOwnershipEnvelope
    left_digest: Sha256Digest
    right_digest: Sha256Digest
    outcome: D0ObservationOutcome | D0ProposalOutcome | PostWriteOutcome
    device_writes: Literal[0] = 0

    @model_validator(mode="after")
    def exact_subject(self) -> ManagedStateComparison:
        if self.ownership_envelope.vertical is not self.vertical:
            raise ValueError("managed-state comparison subject disagrees")
        return self


class ManagedStateAcceptanceEvidence(BaseModel):
    """Secret-free intrinsic evidence for one explicit accepted state."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    acceptance_mode: ManagedStateAcceptanceMode
    accepted_at: datetime
    vertical: ManagedVertical
    ownership_envelope: ManagedOwnershipEnvelope
    canonical_state: ManagedStateSnapshot
    canonical_state_digest: Sha256Digest
    source_git_commit: GitCommit
    source_observation_evidence_digest: Sha256Digest
    previous_accepted_state: AcceptedManagedStateRef | None = None
    postwrite_convergence: ManagedStateComparison | None = None
    digest: Sha256Digest

    def calculated_digest(self) -> str:
        return sha256_identity(
            canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))
        )

    @model_validator(mode="after")
    def exact_bindings(self) -> ManagedStateAcceptanceEvidence:
        if self.schema_version != "1":
            raise ValueError("managed-state acceptance schema is unsupported")
        if (
            self.accepted_at.tzinfo is None
            or self.accepted_at.utcoffset() != UTC.utcoffset(self.accepted_at)
        ):
            raise ValueError("managed-state acceptance time must be UTC")
        state = _validate_state(self.canonical_state)
        if (
            self.vertical is not state.vertical
            or self.ownership_envelope != state.ownership_envelope
            or self.canonical_state_digest != state.digest
        ):
            raise ValueError("managed-state acceptance bindings disagree")
        if self.acceptance_mode is ManagedStateAcceptanceMode.INITIAL_ADOPTION:
            if (
                self.previous_accepted_state is not None
                or self.postwrite_convergence is not None
            ):
                raise ValueError(
                    "initial adoption cannot have a predecessor or convergence proof"
                )
        elif self.previous_accepted_state is None or self.postwrite_convergence is None:
            raise ValueError(
                "post-write acceptance requires a predecessor and convergence proof"
            )
        if self.previous_accepted_state is not None:
            previous = self.previous_accepted_state
            expected_identity = (
                f"managed-state:acceptance:{self.vertical.value}:"
                f"{previous.acceptance_evidence.digest}"
            )
            if (
                previous.ownership_envelope != self.ownership_envelope
                or previous.acceptance_evidence.identity != expected_identity
            ):
                raise ValueError("previous accepted-state reference is not canonical")
        if self.postwrite_convergence is not None:
            comparison = self.postwrite_convergence
            if (
                comparison.outcome is not PostWriteOutcome.CONVERGED
                or comparison.vertical is not self.vertical
                or comparison.ownership_envelope != self.ownership_envelope
                or comparison.left_digest != self.canonical_state_digest
                or comparison.right_digest != self.canonical_state_digest
                or comparison.device_writes != 0
            ):
                raise ValueError(
                    "post-write acceptance does not prove converged O-prime and D1"
                )
        if self.digest != self.calculated_digest():
            raise ValueError("managed-state acceptance evidence digest is invalid")
        return self


def _build_acceptance_evidence(
    *,
    acceptance_mode: ManagedStateAcceptanceMode,
    accepted_at: datetime,
    canonical_state: ManagedStateSnapshot,
    source_git_commit: str,
    source_observation_evidence_digest: str,
    previous_accepted_state: AcceptedManagedStateRef | None = None,
    postwrite_convergence: ManagedStateComparison | None = None,
) -> ManagedStateAcceptanceEvidence:
    unsigned = ManagedStateAcceptanceEvidence.model_construct(
        schema_version="1",
        acceptance_mode=acceptance_mode,
        accepted_at=accepted_at,
        vertical=canonical_state.vertical,
        ownership_envelope=canonical_state.ownership_envelope,
        canonical_state=canonical_state,
        canonical_state_digest=canonical_state.digest,
        source_git_commit=source_git_commit,
        source_observation_evidence_digest=source_observation_evidence_digest,
        previous_accepted_state=previous_accepted_state,
        postwrite_convergence=postwrite_convergence,
        digest="sha256:" + "0" * 64,
    )
    payload = unsigned.model_dump(mode="json")
    payload["digest"] = unsigned.calculated_digest()
    return ManagedStateAcceptanceEvidence.model_validate(payload)


def build_initial_adoption_evidence(
    *,
    accepted_at: datetime,
    observed_state: ManagedStateSnapshot,
    source_git_commit: str,
    source_observation_evidence_digest: str,
) -> ManagedStateAcceptanceEvidence:
    """Explicitly adopt fresh observed reality as generation-one D0 evidence."""
    observed_state = _validate_state(observed_state)
    return _build_acceptance_evidence(
        acceptance_mode=ManagedStateAcceptanceMode.INITIAL_ADOPTION,
        accepted_at=accepted_at,
        canonical_state=observed_state,
        source_git_commit=source_git_commit,
        source_observation_evidence_digest=source_observation_evidence_digest,
    )


def build_postwrite_validated_evidence(
    *,
    accepted_at: datetime,
    postwrite_state: ManagedStateSnapshot,
    reviewed_desired_state: ManagedStateSnapshot,
    previous_accepted_state: AcceptedManagedStateRef,
    source_git_commit: str,
    source_observation_evidence_digest: str,
) -> ManagedStateAcceptanceEvidence:
    """Build advancement evidence only after subject-bound O-prime/D1 convergence."""
    postwrite_state = _validate_state(postwrite_state)
    reviewed_desired_state = _validate_state(reviewed_desired_state)
    comparison = compare_postwrite_to_d1(postwrite_state, reviewed_desired_state)
    if comparison.outcome is not PostWriteOutcome.CONVERGED:
        raise ManagedStateStoreError(
            "post-write managed state did not converge to reviewed D1"
        )
    return _build_acceptance_evidence(
        acceptance_mode=ManagedStateAcceptanceMode.POST_WRITE_VALIDATED,
        accepted_at=accepted_at,
        canonical_state=postwrite_state,
        source_git_commit=source_git_commit,
        source_observation_evidence_digest=source_observation_evidence_digest,
        previous_accepted_state=previous_accepted_state,
        postwrite_convergence=comparison,
    )


def derive_accepted_managed_state_ref(
    evidence: ManagedStateAcceptanceEvidence,
) -> AcceptedManagedStateRef:
    evidence = ManagedStateAcceptanceEvidence.model_validate(
        evidence.model_dump(mode="json")
    )
    return AcceptedManagedStateRef(
        ownership_envelope=evidence.ownership_envelope,
        normalized_accepted_desired_state_digest=evidence.canonical_state_digest,
        source_git_commit=evidence.source_git_commit,
        acceptance_evidence=AcceptanceEvidenceReference(
            identity=(
                f"managed-state:acceptance:{evidence.vertical.value}:{evidence.digest}"
            ),
            digest=evidence.digest,
        ),
    )


class ManagedStateAcceptanceRecord(BaseModel):
    """One immutable link in a per-vertical accepted-state chain."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    vertical: ManagedVertical
    generation: int = Field(ge=1)
    evidence: ManagedStateAcceptanceEvidence
    accepted_state_ref: AcceptedManagedStateRef
    previous_record_digest: Sha256Digest | None = None
    digest: Sha256Digest

    def calculated_digest(self) -> str:
        return sha256_identity(
            canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))
        )

    @model_validator(mode="after")
    def exact_chain_link(self) -> ManagedStateAcceptanceRecord:
        if self.schema_version != "1":
            raise ValueError("managed-state record schema is unsupported")
        if self.vertical is not self.evidence.vertical:
            raise ValueError("managed-state record vertical disagrees")
        if self.accepted_state_ref != derive_accepted_managed_state_ref(self.evidence):
            raise ValueError("accepted managed-state reference is not derived")
        if self.generation == 1:
            if (
                self.evidence.acceptance_mode
                is not ManagedStateAcceptanceMode.INITIAL_ADOPTION
                or self.previous_record_digest is not None
            ):
                raise ValueError("generation one must be an initial adoption")
        elif (
            self.evidence.acceptance_mode
            is not ManagedStateAcceptanceMode.POST_WRITE_VALIDATED
            or self.previous_record_digest is None
        ):
            raise ValueError("later generations require post-write validation")
        if self.digest != self.calculated_digest():
            raise ValueError("managed-state record digest is invalid")
        return self


def _build_record(
    evidence: ManagedStateAcceptanceEvidence,
    *,
    generation: int,
    previous_record_digest: str | None,
) -> ManagedStateAcceptanceRecord:
    unsigned = ManagedStateAcceptanceRecord.model_construct(
        schema_version="1",
        vertical=evidence.vertical,
        generation=generation,
        evidence=evidence,
        accepted_state_ref=derive_accepted_managed_state_ref(evidence),
        previous_record_digest=previous_record_digest,
        digest="sha256:" + "0" * 64,
    )
    payload = unsigned.model_dump(mode="json")
    payload["digest"] = unsigned.calculated_digest()
    return ManagedStateAcceptanceRecord.model_validate(payload)


class ManagedStateResolutionStatus(StrEnum):
    UNINITIALIZED = "uninitialized"
    INITIALIZED = "initialized"


class ManagedStateResolution(BaseModel):
    """A fully validated chain resolution, not an mtime/current-file pointer."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    status: ManagedStateResolutionStatus
    vertical: ManagedVertical
    records: tuple[ManagedStateAcceptanceRecord, ...] = ()

    @model_validator(mode="after")
    def valid_resolution(self) -> ManagedStateResolution:
        if self.status is ManagedStateResolutionStatus.UNINITIALIZED:
            if self.records:
                raise ValueError("uninitialized managed state has records")
            return self
        if not self.records:
            raise ValueError("initialized managed state has no records")
        _validate_chain(self.vertical, self.records)
        return self

    @property
    def head(self) -> ManagedStateAcceptanceRecord:
        if self.status is not ManagedStateResolutionStatus.INITIALIZED:
            raise ManagedStateStoreError("managed state is uninitialized")
        return self.records[-1]

    @property
    def accepted_state_ref(self) -> AcceptedManagedStateRef:
        return self.head.accepted_state_ref

    @property
    def canonical_state(self) -> ManagedStateSnapshot:
        return self.head.evidence.canonical_state


def _validate_chain(
    vertical: ManagedVertical, records: tuple[ManagedStateAcceptanceRecord, ...]
) -> None:
    ordered = tuple(sorted(records, key=lambda item: item.generation))
    if records != ordered:
        raise ValueError("managed-state chain is not generation ordered")
    for index, record in enumerate(records, start=1):
        record = ManagedStateAcceptanceRecord.model_validate(
            record.model_dump(mode="json")
        )
        if record.vertical is not vertical or record.generation != index:
            raise ValueError("managed-state chain has a gap or wrong vertical")
        if index == 1:
            continue
        previous = records[index - 2]
        if (
            record.previous_record_digest != previous.digest
            or record.evidence.previous_accepted_state != previous.accepted_state_ref
        ):
            raise ValueError("managed-state chain predecessor is broken")


def _same_subject(
    left: ManagedStateSnapshot, right: ManagedStateSnapshot
) -> tuple[ManagedStateSnapshot, ManagedStateSnapshot]:
    left = _validate_state(left)
    right = _validate_state(right)
    if (
        left.vertical is not right.vertical
        or left.ownership_envelope != right.ownership_envelope
    ):
        raise ManagedStateStoreError("managed-state comparison subject differs")
    return left, right


def reconcile_d0_to_observation(
    d0: ManagedStateResolution, observed: ManagedStateSnapshot
) -> ManagedStateComparison:
    d0 = ManagedStateResolution.model_validate(d0.model_dump(mode="json"))
    accepted = d0.canonical_state
    accepted, observed = _same_subject(accepted, observed)
    outcome = (
        D0ObservationOutcome.IN_SYNC
        if accepted.digest == observed.digest
        else D0ObservationOutcome.DRIFT_DETECTED
    )
    return ManagedStateComparison(
        vertical=accepted.vertical,
        ownership_envelope=accepted.ownership_envelope,
        left_digest=accepted.digest,
        right_digest=observed.digest,
        outcome=outcome,
    )


def compare_d0_to_d1(
    d0: ManagedStateResolution, desired: ManagedStateSnapshot
) -> ManagedStateComparison:
    d0 = ManagedStateResolution.model_validate(d0.model_dump(mode="json"))
    accepted = d0.canonical_state
    accepted, desired = _same_subject(accepted, desired)
    outcome = (
        D0ProposalOutcome.NO_CHANGE
        if accepted.digest == desired.digest
        else D0ProposalOutcome.CHANGE_PROPOSED
    )
    return ManagedStateComparison(
        vertical=accepted.vertical,
        ownership_envelope=accepted.ownership_envelope,
        left_digest=accepted.digest,
        right_digest=desired.digest,
        outcome=outcome,
    )


def compare_postwrite_to_d1(
    postwrite: ManagedStateSnapshot, desired: ManagedStateSnapshot
) -> ManagedStateComparison:
    postwrite, desired = _same_subject(postwrite, desired)
    outcome = (
        PostWriteOutcome.CONVERGED
        if postwrite.digest == desired.digest
        else PostWriteOutcome.POST_VALIDATION_FAILED
    )
    return ManagedStateComparison(
        vertical=desired.vertical,
        ownership_envelope=desired.ownership_envelope,
        left_digest=postwrite.digest,
        right_digest=desired.digest,
        outcome=outcome,
    )


class ManagedStateStore:
    """Private content-addressed store with one validated chain per vertical."""

    def __init__(self, root: Path, *, checkout: Path, create: bool = True) -> None:
        self._uid = os.getuid()
        self._create = create
        self.root = self._validate_root(root, checkout)
        metadata = self.root.stat(follow_symlinks=False)
        self._root_identity = (metadata.st_dev, metadata.st_ino)
        self._accepted = self._managed_directory(self.root / "accepted")
        self._vertical_directories = {
            vertical: self._managed_directory(self._accepted / vertical.value)
            for vertical in ManagedVertical
        }
        self._validate_directory_population()

    @staticmethod
    def _validate_root(root: Path, checkout: Path) -> Path:
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise ManagedStateStoreError("managed-state store root is invalid")
        if not checkout.is_absolute() or not checkout.is_dir():
            raise ManagedStateStoreError("managed-state checkout context is invalid")
        resolved = root.resolve(strict=True)
        checkout_resolved = checkout.resolve(strict=True)
        if resolved == checkout_resolved or resolved.is_relative_to(checkout_resolved):
            raise ManagedStateStoreError("managed-state store must be outside checkout")
        metadata = root.stat(follow_symlinks=False)
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise ManagedStateStoreError("managed-state store root is not private")
        return resolved

    def _validate_root_identity(self) -> None:
        metadata = self.root.stat(follow_symlinks=False)
        if (
            self.root.is_symlink()
            or not self.root.is_dir()
            or metadata.st_uid != self._uid
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or (metadata.st_dev, metadata.st_ino) != self._root_identity
        ):
            raise ManagedStateStoreError("managed-state store root changed")

    def _managed_directory(self, path: Path) -> Path:
        if self._create:
            with suppress(FileExistsError):
                path.mkdir(mode=0o700)
        self._validate_managed_directory(path)
        return path

    def _validate_managed_directory(self, path: Path) -> None:
        if path.is_symlink() or not path.is_dir():
            raise ManagedStateStoreError("managed-state directory is unsafe")
        metadata = path.stat(follow_symlinks=False)
        if metadata.st_uid != self._uid or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise ManagedStateStoreError("managed-state directory is not private")
        try:
            path.resolve(strict=True).relative_to(self.root)
        except ValueError:
            raise ManagedStateStoreError(
                "managed-state directory escapes root"
            ) from None

    def _validate_directory_population(self) -> None:
        self._validate_managed_directory(self._accepted)
        root_entries = tuple(os.scandir(self.root))
        root_names = {entry.name for entry in root_entries}
        if root_names != {"accepted"}:
            raise ManagedStateStoreError(
                "managed-state root contains unexpected entries"
            )
        if any(
            entry.is_symlink() or not entry.is_dir(follow_symlinks=False)
            for entry in root_entries
        ):
            raise ManagedStateStoreError("managed-state root entry is unsafe")
        vertical_entries = tuple(os.scandir(self._accepted))
        vertical_names = {entry.name for entry in vertical_entries}
        if vertical_names != {item.value for item in ManagedVertical}:
            raise ManagedStateStoreError(
                "managed-state vertical directories are not exact"
            )
        if any(
            entry.is_symlink() or not entry.is_dir(follow_symlinks=False)
            for entry in vertical_entries
        ):
            raise ManagedStateStoreError("managed-state vertical directory is unsafe")
        for directory in self._vertical_directories.values():
            self._validate_managed_directory(directory)

    def _read_record(
        self, vertical: ManagedVertical, path: Path
    ) -> ManagedStateAcceptanceRecord:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as error:
            raise ManagedStateStoreError(
                "managed-state record is missing or unsafe"
            ) from error
        try:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != self._uid
                or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_size > MAX_MANAGED_STATE_RECORD_BYTES
            ):
                raise ManagedStateStoreError("managed-state record metadata is invalid")
            content = b""
            while len(content) < before.st_size:
                chunk = os.read(descriptor, min(65536, before.st_size - len(content)))
                if not chunk:
                    raise ManagedStateStoreError(
                        "managed-state record changed during read"
                    )
                content += chunk
            if os.read(descriptor, 1):
                raise ManagedStateStoreError(
                    "managed-state record exceeds bounded size"
                )
            after = os.fstat(descriptor)
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ManagedStateStoreError("managed-state record changed during read")
        finally:
            os.close(descriptor)
        try:
            record = ManagedStateAcceptanceRecord.model_validate_json(content)
        except ValidationError as error:
            raise ManagedStateStoreError(
                "managed-state record schema is invalid"
            ) from error
        if (
            record.vertical is not vertical
            or path.name != f"{record.digest[7:]}.json"
            or canonical_json_bytes(record.model_dump(mode="json")) != content
        ):
            raise ManagedStateStoreError("managed-state record integrity is invalid")
        return record

    def _records(
        self, vertical: ManagedVertical
    ) -> tuple[ManagedStateAcceptanceRecord, ...]:
        self._validate_root_identity()
        self._validate_directory_population()
        directory = self._vertical_directories[vertical]
        records: list[ManagedStateAcceptanceRecord] = []
        for entry in os.scandir(directory):
            if entry.name.startswith(".managed-state-tmp-"):
                continue
            match = _RECORD_NAME.fullmatch(entry.name)
            if (
                match is None
                or entry.is_symlink()
                or not entry.is_file(follow_symlinks=False)
            ):
                raise ManagedStateStoreError(
                    "managed-state directory contains an unexpected entry"
                )
            records.append(self._read_record(vertical, Path(entry.path)))
            if len(records) > MAX_MANAGED_STATE_RECORD_SCAN:
                raise ManagedStateStoreError("managed-state record scan bound exceeded")
        ordered = tuple(sorted(records, key=lambda item: item.generation))
        try:
            _validate_chain(vertical, ordered)
        except ValueError as error:
            raise ManagedStateStoreError("managed-state chain is invalid") from error
        return ordered

    def resolve_current_d0(self, vertical: ManagedVertical) -> ManagedStateResolution:
        try:
            vertical = ManagedVertical(vertical)
        except ValueError:
            raise ManagedStateStoreError(
                "managed-state vertical is unsupported"
            ) from None
        records = self._records(vertical)
        return ManagedStateResolution(
            status=(
                ManagedStateResolutionStatus.INITIALIZED
                if records
                else ManagedStateResolutionStatus.UNINITIALIZED
            ),
            vertical=vertical,
            records=records,
        )

    def persist_acceptance(
        self, evidence: ManagedStateAcceptanceEvidence
    ) -> ManagedStateAcceptanceRecord:
        if not self._create:
            raise ManagedStateStoreError("managed-state store is read-only")
        evidence = ManagedStateAcceptanceEvidence.model_validate(
            evidence.model_dump(mode="json")
        )
        resolution = self.resolve_current_d0(evidence.vertical)
        for existing in resolution.records:
            if existing.evidence == evidence:
                if existing == resolution.head:
                    return existing
                raise ManagedStateStoreError(
                    "managed-state acceptance is historical, not the current head"
                )
        if resolution.status is ManagedStateResolutionStatus.UNINITIALIZED:
            generation = 1
            previous_digest = None
        else:
            if evidence.previous_accepted_state != resolution.accepted_state_ref:
                raise ManagedStateStoreError(
                    "managed-state acceptance does not extend the head"
                )
            generation = resolution.head.generation + 1
            previous_digest = resolution.head.digest
        record = _build_record(
            evidence, generation=generation, previous_record_digest=previous_digest
        )
        content = canonical_json_bytes(record.model_dump(mode="json"))
        if len(content) > MAX_MANAGED_STATE_RECORD_BYTES:
            raise ManagedStateStoreError("managed-state record exceeds bounded size")
        directory = self._vertical_directories[evidence.vertical]
        destination = directory / f"{record.digest[7:]}.json"
        if destination.exists() or destination.is_symlink():
            existing = self._read_record(evidence.vertical, destination)
            if existing != record:
                raise ManagedStateStoreError("managed-state record digest collision")
            return existing
        try:
            self._publish_new(directory, destination.name, content)
        except FileExistsError:
            existing = self._read_record(evidence.vertical, destination)
            if existing != record:
                raise ManagedStateStoreError(
                    "managed-state record publication raced"
                ) from None
        return record

    @staticmethod
    def _publish_new(directory: Path, final_name: str, content: bytes) -> None:
        directory_flags = (
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            directory_fd = os.open(directory, directory_flags)
        except OSError as error:
            raise ManagedStateStoreError(
                "managed-state publication directory is unsafe"
            ) from error
        temporary_name = f".managed-state-tmp-{uuid4()}"
        file_fd: int | None = None
        linked = False
        try:
            file_fd = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
            view = memoryview(content)
            while view:
                written = os.write(file_fd, view)
                if written <= 0:
                    raise ManagedStateStoreError("managed-state write did not complete")
                view = view[written:]
            os.fsync(file_fd)
            os.close(file_fd)
            file_fd = None
            os.link(
                temporary_name,
                final_name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
            linked = True
            os.fsync(directory_fd)
        except OSError as error:
            if linked:
                with suppress(OSError):
                    os.unlink(final_name, dir_fd=directory_fd)
            if error.errno == errno.EEXIST:
                raise FileExistsError(final_name) from None
            raise ManagedStateStoreError("managed-state publication failed") from error
        finally:
            if file_fd is not None:
                os.close(file_fd)
            with suppress(OSError):
                os.unlink(temporary_name, dir_fd=directory_fd)
            os.close(directory_fd)
