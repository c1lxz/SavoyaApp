from __future__ import annotations

import os

from backend.app.services.gate_controller import GateController


def _parse_targets() -> list[tuple[str, int]]:
    raw = os.getenv("GATE_CONNECTIVITY_TARGETS", "").strip()
    targets: list[tuple[str, int]] = []
    if raw:
        for item in raw.split(","):
            host, _, port = item.strip().partition(":")
            if host and port:
                targets.append((host.strip(), int(port.strip())))
        return targets

    defaults = [
        (os.getenv("GATE_GATESERV_HOST", "127.0.0.1").strip(), int(os.getenv("GATE_GATESERV_PORT", "1917"))),
    ]
    return defaults


if __name__ == "__main__":
    controller = GateController.from_env()
    for host, port in _parse_targets():
        result = controller.check_connectivity(host, port)
        if result["reachable"]:
            print(f"OK {host}:{port} reachable in {result['latency_ms']} ms")
        else:
            print(f"FAIL {host}:{port} {result['error']}")
