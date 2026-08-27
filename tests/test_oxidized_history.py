"""Private Oxidized Git chronology metadata-reader tests."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC
from pathlib import Path

import pytest

from network_change_delivery.configuration_observation import OxidizedRevision
from network_change_delivery.oxidized_history import (
    GIT_EXECUTABLE,
    GIT_MAX_OUTPUT_BYTES,
    GIT_TIMEOUT_SECONDS,
    OXIDIZED_GIT_AUTHOR,
    OXIDIZED_GIT_EMAIL,
    OXIDIZED_GROUP,
    OXIDIZED_HISTORY_DIRECTORY,
    OXIDIZED_REPOSITORY_IDENTITY,
    OxidizedHistoryError,
    OxidizedHistoryRepository,
    canonical_config_path,
)

pytestmark = pytest.mark.skipif(
    not Path(GIT_EXECUTABLE).is_file(), reason="fixed Git executable unavailable"
)


def git(*arguments: str, cwd: Path | None = None, env: dict[str, str] | None = None):
    return subprocess.run(
        [GIT_EXECUTABLE, *arguments],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
    )


def chronology(tmp_path: Path, *, symlink_node: bool = False) -> tuple[Path, list[str]]:
    repository = tmp_path / OXIDIZED_HISTORY_DIRECTORY
    git("init", "--bare", str(repository))
    repository.chmod(0o700)
    work = tmp_path / "work"
    git("init", str(work))
    git("config", "user.name", OXIDIZED_GIT_AUTHOR, cwd=work)
    git("config", "user.email", OXIDIZED_GIT_EMAIL, cwd=work)
    managed = work / OXIDIZED_GROUP
    managed.mkdir()
    node1 = managed / "netbox-device-1"
    node1.write_text("! synthetic chronology\nnode one\nversion A\n")
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2026-08-27T01:00:00Z",
        "GIT_COMMITTER_DATE": "2026-08-27T01:00:00Z",
    }
    git("add", ".", cwd=work)
    git("commit", "-m", "synthetic node1 A", cwd=work, env=env)
    commits = [git("rev-parse", "HEAD", cwd=work).stdout.decode().strip()]
    node1.write_text("! synthetic chronology\nnode one\nversion B\n")
    env.update(
        GIT_AUTHOR_DATE="2026-08-27T02:00:00Z",
        GIT_COMMITTER_DATE="2026-08-27T02:00:00Z",
    )
    git("add", ".", cwd=work)
    git("commit", "-m", "synthetic node1 B", cwd=work, env=env)
    commits.append(git("rev-parse", "HEAD", cwd=work).stdout.decode().strip())
    node2 = managed / "netbox-device-2"
    if symlink_node:
        node2.symlink_to("netbox-device-1")
    else:
        node2.write_text("! synthetic chronology\nnode two\nversion A\n")
    env.update(
        GIT_AUTHOR_DATE="2026-08-27T03:00:00Z",
        GIT_COMMITTER_DATE="2026-08-27T03:00:00Z",
    )
    git("add", ".", cwd=work)
    git("commit", "-m", "synthetic node2 A", cwd=work, env=env)
    commits.append(git("rev-parse", "HEAD", cwd=work).stdout.decode().strip())
    git("push", str(repository), "HEAD:main", cwd=work)
    git(f"--git-dir={repository}", "symbolic-ref", "HEAD", "refs/heads/main")
    return repository, commits


@pytest.mark.parametrize(
    ("node", "group"),
    [
        ("core-02", "managed"),
        ("netbox-device-0", "managed"),
        ("../netbox-device-1", "managed"),
        ("/netbox-device-1", "managed"),
        ("netbox-device-1", "other"),
        ("netbox-device-1", "../managed"),
    ],
)
def test_canonical_path_rejects_unreviewed_identities(node: str, group: str) -> None:
    with pytest.raises(OxidizedHistoryError, match="identity rejected"):
        canonical_config_path(node, group)


def test_contract_constants_are_frozen() -> None:
    assert OXIDIZED_REPOSITORY_IDENTITY == "oxidized:ncdp-lab-actual-state"
    assert OXIDIZED_GIT_AUTHOR == "NCDP Oxidized"
    assert OXIDIZED_GIT_EMAIL == "oxidized@ncdp.local"
    assert canonical_config_path("netbox-device-1") == "managed/netbox-device-1"
    assert canonical_config_path("netbox-device-2") == "managed/netbox-device-2"


def test_latest_revision_is_path_scoped_and_schema_compatible(tmp_path: Path) -> None:
    repository, commits = chronology(tmp_path)
    node1 = OxidizedHistoryRepository(repository).latest_revision("netbox-device-1")
    node2 = OxidizedHistoryRepository(repository).latest_revision("netbox-device-2")
    assert isinstance(node1, OxidizedRevision)
    assert node1.commit == commits[1]
    assert node2.commit == commits[2]
    assert node1.commit != commits[2]
    assert node1.config_path == "managed/netbox-device-1"
    assert node2.config_path == "managed/netbox-device-2"
    assert len(node1.commit) == len(node1.blob) == 40
    assert node1.collected_at.tzinfo is UTC
    assert node1.collected_at.isoformat() == "2026-08-27T02:00:00+00:00"


@pytest.mark.parametrize(
    "kind", ["relative", "checkout", "audit", "symlink", "mode", "owner"]
)
def test_repository_boundary_rejects_unsafe_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    repository, _ = chronology(tmp_path)
    candidate = repository
    if kind == "relative":
        candidate = Path("config-history.git")
    elif kind == "checkout":
        candidate = Path(__file__).parents[1]
    elif kind == "audit":
        candidate = tmp_path / "audit" / "config-history.git"
    elif kind == "symlink":
        candidate = tmp_path / "history-link"
        candidate.symlink_to(repository, target_is_directory=True)
    elif kind == "mode":
        repository.chmod(0o750)
    elif kind == "owner":
        monkeypatch.setattr(os, "getuid", lambda: repository.stat().st_uid + 1)
    with pytest.raises(OxidizedHistoryError):
        OxidizedHistoryRepository(candidate).latest_revision("netbox-device-1")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("remote.origin.url", "/private/remote"),
        ("remote.origin.pushurl", "/private/push-only"),
        ("remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"),
    ],
)
def test_any_local_remote_namespace_is_rejected(
    tmp_path: Path, key: str, value: str
) -> None:
    repository, _ = chronology(tmp_path)
    git(f"--git-dir={repository}", "config", "--local", key, value)
    with pytest.raises(OxidizedHistoryError, match="repository rejected"):
        OxidizedHistoryRepository(repository).latest_revision("netbox-device-1")


def test_clean_repository_without_remote_namespace_is_accepted(tmp_path: Path) -> None:
    repository, commits = chronology(tmp_path)
    revision = OxidizedHistoryRepository(repository).latest_revision("netbox-device-1")
    assert revision.commit == commits[1]


def test_nonbare_empty_missing_replace_and_alternates_fail_closed(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.git"
    with pytest.raises(OxidizedHistoryError):
        OxidizedHistoryRepository(missing).latest_revision("netbox-device-1")
    empty = tmp_path / "empty.git"
    git("init", "--bare", str(empty))
    empty.chmod(0o700)
    with pytest.raises(OxidizedHistoryError):
        OxidizedHistoryRepository(empty).latest_revision("netbox-device-1")
    nonbare = tmp_path / "nonbare"
    git("init", str(nonbare))
    nonbare.chmod(0o700)
    with pytest.raises(OxidizedHistoryError):
        OxidizedHistoryRepository(nonbare).latest_revision("netbox-device-1")

    for boundary in ("replace", "alternates"):
        repository, commits = chronology(tmp_path / boundary)
        if boundary == "replace":
            git(
                f"--git-dir={repository}",
                "update-ref",
                f"refs/replace/{commits[0]}",
                commits[1],
            )
        else:
            alternates = repository / "objects" / "info" / "alternates"
            alternates.write_text("/private/objects\n")
        with pytest.raises(OxidizedHistoryError, match="repository rejected"):
            OxidizedHistoryRepository(repository).latest_revision("netbox-device-1")


def test_missing_path_and_non_blob_entry_fail_closed(tmp_path: Path) -> None:
    repository, _ = chronology(tmp_path / "missing")
    with pytest.raises(OxidizedHistoryError, match="unavailable"):
        OxidizedHistoryRepository(repository).latest_revision("netbox-device-99")
    symlink_repository, _ = chronology(tmp_path / "symlink", symlink_node=True)
    with pytest.raises(OxidizedHistoryError, match="unavailable"):
        OxidizedHistoryRepository(symlink_repository).latest_revision("netbox-device-2")


@pytest.mark.parametrize(
    "log_output",
    [
        b"not-an-oid\x002026-08-27T00:00:00Z\n",
        b"a" * 40 + b"\x00not-a-time\n",
        b"a" * 40 + b"\x002026-08-27T00:00:00\n",
    ],
)
def test_malformed_oid_and_timestamp_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, log_output: bytes
) -> None:
    repository, _ = chronology(tmp_path)
    reader = OxidizedHistoryRepository(repository)
    monkeypatch.setattr(reader, "_validate_repository", lambda: None)
    monkeypatch.setattr(reader, "_git", lambda *_arguments: log_output)
    with pytest.raises(OxidizedHistoryError, match="unavailable"):
        reader.latest_revision("netbox-device-1")


def test_malformed_tree_entry_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, commits = chronology(tmp_path)
    reader = OxidizedHistoryRepository(repository)
    monkeypatch.setattr(reader, "_validate_repository", lambda: None)
    responses = iter(
        [
            f"{commits[-1]}\x002026-08-27T03:00:00Z\n".encode(),
            b"100644 blob malformed\tmanaged/netbox-device-1\x00",
        ]
    )
    monkeypatch.setattr(reader, "_git", lambda *_arguments: next(responses))
    with pytest.raises(OxidizedHistoryError, match="unavailable"):
        reader.latest_revision("netbox-device-1")


def test_reader_subprocess_and_privacy_contract_is_bounded() -> None:
    source = (
        Path(__file__).parents[1] / "src/network_change_delivery/oxidized_history.py"
    ).read_text()
    assert "shell=False" in source
    assert "timeout=GIT_TIMEOUT_SECONDS" in source
    assert GIT_TIMEOUT_SECONDS == 5
    assert GIT_MAX_OUTPUT_BYTES == 4096
    assert "GIT_TERMINAL_PROMPT" in source
    assert "GIT_CONFIG_NOSYSTEM" in source
    assert "GIT_NO_REPLACE_OBJECTS" in source
    assert '"log",' in source and '"--",' in source
    for forbidden in ("git show", "log -p", "git diff", "cat-file", "blob.data"):
        assert forbidden not in source


def test_real_writer_harness_freezes_reviewed_git_contract() -> None:
    root = Path(__file__).parents[1]
    harness = (root / "scripts/oxidized/git_chronology_harness.rb").read_text()
    verifier = (root / "scripts/oxidized/verify_git_chronology.sh").read_text()
    assert "Oxidized::Output::Git.new" in harness
    assert "writer.store(" in harness
    assert "update_repo" not in harness
    assert "single_repo = true" in harness
    assert "type_as_directory = false" in harness
    assert "NCDP Oxidized" in harness
    assert "oxidized@ncdp.local" in harness
    assert "clean_obsolete_nodes" not in harness
    assert "--network none" in verifier
    assert "--read-only" in verifier
    assert "--cap-drop ALL" in verifier
    assert "no-new-privileges" in verifier
    assert "router.json" not in verifier
