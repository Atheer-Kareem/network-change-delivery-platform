from pybatfish.client.session import Session

session = Session(host="127.0.0.1", port=9996)
version = session._get_bf_version()
if not version:
    raise RuntimeError("Batfish server version unavailable")
print(f"Batfish ready: {version}")
