"""Start the loopback dashboard with a single durable job worker."""

import argparse
import os
import sys

import uvicorn

from sellbird.dashboard_auth import TokenStore, is_loopback

from .app import DATA, create_app


def reject_external_socket(event, args):
    if event == "socket.getaddrinfo":
        host = args[0]
    elif event == "socket.connect":
        address = args[1]
        host = address[0] if isinstance(address, tuple) else None
    else:
        return
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="replace")
    if host is not None and not is_loopback(host):
        raise PermissionError("Offline mode blocks connections to non-loopback hosts.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--offline", action="store_true", help="Disable public-page capture and external Python socket connections.")
    args = parser.parse_args()
    if args.offline:
        os.environ["SELLBIRD_LOCAL_OFFLINE"] = "1"
        sys.addaudithook(reject_external_socket)
    DATA.mkdir(parents=True, exist_ok=True)
    token = TokenStore(DATA / "dashboard-token").get()
    print(f"Open http://127.0.0.1:{args.port}/#token={token}", flush=True)
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port, workers=1, proxy_headers=False)


if __name__ == "__main__":
    main()
