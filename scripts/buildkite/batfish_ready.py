import os

from pybatfish.client.session import Session


def batfish_host() -> str:
    return os.environ.get("NCDP_BATFISH_HOST", "127.0.0.1")


def check_batfish() -> str:
    session = Session(host=batfish_host(), port=9996)
    version = session._get_bf_version()
    if not version:
        raise RuntimeError("Batfish server version unavailable")
    return version


if __name__ == "__main__":
    print(f"Batfish ready: {check_batfish()}")
