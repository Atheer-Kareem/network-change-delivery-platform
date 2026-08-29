"""Private, atomic SNMP exporter authentication publication."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import yaml

from network_change_delivery.observability_private_paths import (
    ObservabilityPrivatePathError,
    ensure_private_tree,
    validate_private_file,
)

AUTH_FILENAME = "snmp-auth.yml"
AMBIGUITY_GUARD = "auth-publication-ambiguous"
MAX_AUTH_BYTES = 32 * 1024
MAX_AUTHS = 16
_SELECTOR = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_USERNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$")
_AUTH_FIELDS = {
    "version",
    "security_level",
    "username",
    "password",
    "auth_protocol",
    "priv_protocol",
    "priv_password",
}


class SnmpPrivatePublicationError(ValueError):
    """Bounded private-auth publication failure without secret content."""


def validate_auth_content(content: bytes) -> None:
    """Require the exact secret-only authPriv document shape."""
    if not content or len(content) > MAX_AUTH_BYTES:
        raise SnmpPrivatePublicationError("SNMP auth content rejected")
    try:
        value = yaml.safe_load(content)
    except yaml.YAMLError:
        raise SnmpPrivatePublicationError("SNMP auth content rejected") from None
    if not isinstance(value, dict) or set(value) != {"auths"}:
        raise SnmpPrivatePublicationError("SNMP auth authority rejected")
    auths = value["auths"]
    if not isinstance(auths, dict) or not 1 <= len(auths) <= MAX_AUTHS:
        raise SnmpPrivatePublicationError("SNMP auth population rejected")
    for selector, auth in auths.items():
        if (
            not isinstance(selector, str)
            or _SELECTOR.fullmatch(selector) is None
            or not isinstance(auth, dict)
            or set(auth) != _AUTH_FIELDS
            or auth.get("version") != 3
            or auth.get("security_level") != "authPriv"
            or auth.get("auth_protocol") != "SHA256"
            or auth.get("priv_protocol") != "AES"
        ):
            raise SnmpPrivatePublicationError("SNMP auth entry rejected")
        username = auth.get("username")
        password = auth.get("password")
        privacy = auth.get("priv_password")
        if (
            not isinstance(username, str)
            or _USERNAME.fullmatch(username) is None
            or not isinstance(password, str)
            or not 8 <= len(password) <= 128
            or not isinstance(privacy, str)
            or not 8 <= len(privacy) <= 128
            or "$" in username + password + privacy
        ):
            raise SnmpPrivatePublicationError("SNMP auth entry rejected")


def _atomic_replace(path: Path, content: bytes) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
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
        validate_private_file(path, maximum_bytes=MAX_AUTH_BYTES)
    except OSError as error:
        message = (
            "SNMP auth publication ambiguous"
            if replaced
            else "SNMP auth publication failed"
        )
        raise SnmpPrivatePublicationError(message) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def publish_snmp_auth(directory: Path, content: bytes) -> Path:
    """Atomically replace one auth file within a stable mounted directory."""
    validate_auth_content(content)
    try:
        ensure_private_tree(directory)
        guard = directory / AMBIGUITY_GUARD
        if guard.exists():
            raise SnmpPrivatePublicationError("SNMP auth publication ambiguous")
        current = validate_private_file(
            directory / AUTH_FILENAME,
            missing_ok=True,
            maximum_bytes=MAX_AUTH_BYTES,
        )
        if current is not None:
            validate_auth_content(current)
        _atomic_replace(guard, b"AMBIGUOUS\n")
        _atomic_replace(directory / AUTH_FILENAME, content)
        guard.unlink()
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        validate_published_snmp_auth(directory)
    except ObservabilityPrivatePathError as error:
        raise SnmpPrivatePublicationError("SNMP auth private path rejected") from error
    except OSError as error:
        raise SnmpPrivatePublicationError("SNMP auth publication ambiguous") from error
    return directory / AUTH_FILENAME


def validate_published_snmp_auth(directory: Path) -> bytes:
    """Read a coherent publication while refusing any ambiguity guard."""
    try:
        ensure_private_tree(directory)
        if (directory / AMBIGUITY_GUARD).exists():
            raise SnmpPrivatePublicationError("SNMP auth publication ambiguous")
        content = validate_private_file(
            directory / AUTH_FILENAME, maximum_bytes=MAX_AUTH_BYTES
        )
    except ObservabilityPrivatePathError as error:
        raise SnmpPrivatePublicationError("SNMP auth private path rejected") from error
    assert content is not None
    validate_auth_content(content)
    return content
