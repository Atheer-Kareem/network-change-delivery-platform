import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
CONTEXT = ROOT / "infrastructure" / "oxidized" / "runtime"


def read(name: str) -> str:
    return (CONTEXT / name).read_text()


def test_build_context_is_narrow_and_base_is_immutable() -> None:
    dockerfile = read("Dockerfile")
    assert (
        "ruby:3.3.9-slim-bookworm@sha256:"
        "b084aa6c608f29f4a3b54577884bb7e983abd0852c3650e7ab03f9b46f87151e" in dockerfile
    )
    assert "latest" not in dockerfile.lower()
    assert "COPY ." not in dockerfile
    assert read(".dockerignore").splitlines() == [
        "*",
        "!Dockerfile",
        "!Gemfile",
        "!Gemfile.lock",
    ]
    assert {path.name for path in CONTEXT.iterdir()} == {
        ".dockerignore",
        "Dockerfile",
        "Gemfile",
        "Gemfile.lock",
    }


def test_gem_contract_and_lock_are_exact() -> None:
    gemfile = read("Gemfile")
    lock = read("Gemfile.lock")
    assert 'ruby "3.3.9"' in gemfile
    assert 'gem "oxidized", "= 0.37.0"' in gemfile
    assert 'gem "oxidized-web", "= 0.18.1"' in gemfile
    for dependency in ("oxidized (0.37.0)", "oxidized-web (0.18.1)", "rugged (1.9.6)"):
        assert dependency in lock
    assert "ruby 3.3.9p170" in lock
    assert re.search(r"BUNDLED WITH\n   2\.5\.22\n\Z", lock)
    assert "aarch64-linux" in lock


def test_final_image_is_non_root_and_has_no_build_toolchain() -> None:
    dockerfile = read("Dockerfile")
    runtime = dockerfile.split(" AS runtime\n", maxsplit=1)[1]
    assert "USER 30000:30000" in runtime
    assert "EXPOSE 8888/tcp" in runtime
    assert 'ENTRYPOINT ["bundle", "_2.5.22_", "exec", "oxidized"]' in runtime
    for build_only in ("build-essential", "cmake", "libgit2-dev", "pkg-config"):
        assert build_only not in runtime
    for forbidden in ("PASSWORD", "TOKEN", "SECRET", "CREDENTIAL"):
        assert forbidden not in dockerfile.upper()


def test_synthetic_verifier_is_bounded_and_hardened() -> None:
    verifier = (ROOT / "scripts" / "verify_oxidized_runtime.sh").read_text()
    for contract in (
        "interval: 0",
        "192.0.2.1:ios",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--publish 127.0.0.1::8888",
        '"http://127.0.0.1:${host_port}/nodes.json"',
        '"${attempt}" -lt 30',
        'status == "never"',
        "trap cleanup EXIT HUP INT TERM",
    ):
        assert contract in verifier
    assert "docker.sock" in verifier
    assert "NCDP_OPENBAO_" in verifier
    assert "NCDP_NETBOX_" in verifier
    assert "docker exec" in verifier and "id -u" in verifier
