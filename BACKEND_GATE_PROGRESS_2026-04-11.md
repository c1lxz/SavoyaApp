# Backend Gate Progress — 2026-04-11

## Current state

- Local frontend stabilization is complete enough to continue backend work.
- Local backend test environment is prepared in `.venv`.
- Local regression checks passed:
  - `frontend`: `npm run typecheck`
  - `frontend`: `node frontend/scripts/playwright-responsive-smoke.cjs`
  - `backend`: selected `pytest` suites for access/gate/compatibility

## What is confirmed from the codebase

- API open flow:
  - `backend/app/services/access.py`
  - `backend/app/services/gate.py`
  - `backend/app/scripts/gate_bridge.py`
  - `backend/app/scripts/gate_runtime.py`
- Current implementation creates a Gate MDB user/key, resolves permissions from MDB, then generates a synthetic Wiegand-26 credential in code.
- Current TCP implementation is **direct-to-target** and assumes the backend can send a payload straight to a configured host/port.
- Current payload assumptions are not confirmed by the real server:
  - `json`
  - `payload_hex`
  - `fc_cn`

## What is confirmed from the real server

- Running Gate processes:
  - `C:\GATE\Server\GateServ.exe`
  - `C:\GATE\Terminal\GateTerm.exe`
- `GateServ.exe` is the active TCP hub:
  - listens on local port `1917`
  - keeps persistent outbound TCP connections to controllers on port `5000`
- Confirmed controller/endpoint IPs seen in active connections:
  - `192.168.1.234:5000`
  - `192.168.1.244:5000`
  - `192.168.1.245:5000`
  - `192.168.1.247:5000`
  - `192.168.1.248:5000`
  - `10.118.220.2:5000`
  - `10.118.220.3:5000`
- `127.0.0.1:1917` is reachable locally on the server.
- `GateTerm.exe` is running, but the provided TCP snapshot did not show it owning active TCP sockets.

## Main conclusion

The current backend hypothesis is likely wrong.

Most likely real topology:

`Backend -> local GateServ (1917) -> controllers (5000)`

Less likely topology:

`Backend -> controllers directly on 5000`

Because of that, the existing direct TCP Wiegand sender in `gate_runtime.py` should be treated as provisional and probably incorrect for production.

## What is still unknown

- Exact protocol spoken to `GateServ` on `127.0.0.1:1917`
- Whether `GateServ` expects:
  - raw bytes
  - framed hex text
  - JSON
  - another proprietary message format
- Whether facility/card values should be synthetic, stored, or derived from real Gate data
- Whether `GateTerm` participates in open commands or is only an operator UI/reporting tool

## Safe next engineering move

- Refactor backend to isolate:
  - Wiegand-26 packet building
  - transport selection
  - detailed structured logging
  - dry-run behavior
- Add a dedicated `GateController` abstraction with pluggable transports:
  - `dry_run`
  - `gateserv_tcp`
  - `controller_tcp`
  - `http`
- Keep real send behavior configurable until the `1917` protocol is fully confirmed.

## Remaining server-side evidence that would still help

- Non-log configuration or tool docs referencing port `1917`
- Any read-only evidence of the message format expected by `GateServ`
- Short excerpts from `TcpLog` / `PortLog` / binary strings if needed later

## Additional confirmed evidence

- Vendor manual `gatesrvtrm_1_22_44.pdf` documents TCP port `1917` as the default port for Gate-Monitoring workstations.
- This confirms that `1917` is a real Gate TCP endpoint, but does **not** prove that it is the gate-open command API.
- `TcpLog` on `2026-04-11` logged:
  - `11.04.2026 00:02:26.361 Client 127.0.0.1:63365 Connection accepted`
  - `11.04.2026 00:02:26.362 Client 127.0.0.1:63365 Connection closed`
- This matches a pure TCP connect/close probe and confirms:
  - `GateServ` logs clients on `1917`
  - a bare connection alone does not reveal any payload semantics
- `PortLog` on `2026-04-11` shows repeated `SocketException 10060` retries to `192.168.1.246:5000`.
- This confirms:
  - `GateServ` itself is the active process managing controller TCP connectivity on port `5000`
  - configured controllers exist beyond the currently established socket list
  - controller health and reconnect logic are internal to `GateServ`, not to this backend

## Implemented on 2026-04-11

- Added `backend/app/services/gate_controller.py`
  - isolated Wiegand-26 packet building
  - added pluggable transports: `dry_run`, `gateserv_tcp`, `controller_tcp`, `http`
  - added packet diagnostics:
    - `frame_hex` (legacy 26-bit frame)
    - `payload_hex_be` (4-byte big-endian payload)
    - raw bit string
  - added safe TCP reachability check without sending data
- Refactored `backend/app/scripts/gate_runtime.py`
  - open flow now delegates transport work to `GateController`
  - bridge responses now include structured `details`
- Refactored access logging
  - `access_event_logs.details` now stores `gate_result` diagnostics for each open attempt
  - `AccessKey.protocol_type` now records `gate_mdb_user` instead of `unknown`
- Added safe utilities:
  - `test_wiegand_format.py`
  - `test_tcp_connectivity.py`
- Added tests:
  - `backend/tests/test_gate_controller.py`
  - extended `backend/tests/test_access_api.py` with event diagnostics assertions

## Local verification after refactor

- `.\.venv\Scripts\python -m pytest backend\tests -q`
  - `42 passed`
- `.\.venv\Scripts\python test_wiegand_format.py`
  - packet for `facility=1`, `card=12345`
  - frame hex: `2026073`
  - payload hex big-endian: `02026073`

## Current readiness

- Backend is now structurally ready for tomorrow's live tests:
  - packet generation is deterministic and covered by tests
  - transport behavior is isolated and switchable by env
  - dry-run is explicit and safe
  - each open attempt can now be audited through stored diagnostics
- Still unconfirmed before a real opening attempt:
  - exact production payload format for the real live transport
  - whether the final live path should be `gateserv_tcp` or another server-side bridge/protocol

## Live-test handoff

- The current real-server live-test runbook is fixed in:
  - `GATE_LIVE_TEST_RUNBOOK_2026-04-11.md`
- `.env` is now switched to the first real test hypothesis:
  - `gateserv_tcp`
  - `127.0.0.1:1917`
  - payload format `frame_hex`
  - `DRY_RUN=false`
