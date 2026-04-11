from __future__ import annotations

from backend.app.services.gate_controller import GateController


def _clear_gate_env(monkeypatch) -> None:
    for key in (
        "DRY_RUN",
        "GATE_DRY_RUN",
        "GATE_WIEGAND_DRY_RUN",
        "GATE_WIEGAND_TRANSPORT",
        "GATE_WIEGAND_TIMEOUT_SECONDS",
        "GATE_WIEGAND_TCP_HOST",
        "GATE_WIEGAND_TCP_PORT",
        "GATE_WIEGAND_TCP_PAYLOAD_FORMAT",
        "GATE_WIEGAND_TCP_APPEND_NEWLINE",
        "GATE_WIEGAND_TCP_ENCODING",
        "GATE_GATESERV_HOST",
        "GATE_GATESERV_PORT",
        "GATE_GATESERV_PAYLOAD_FORMAT",
        "GATE_GATESERV_APPEND_NEWLINE",
        "GATE_GATESERV_ENCODING",
        "GATE_WIEGAND_HTTP_URL",
        "GATE_WIEGAND_HTTP_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)


def test_build_wiegand26_packet_known_values() -> None:
    packet = GateController.build_wiegand26_packet(facility_code=1, card_number=12345)

    assert packet.bits == "10000000100110000001110011"
    assert packet.frame == 33710195
    assert packet.frame_hex == "2026073"
    assert packet.payload_hex_be == "02026073"
    assert packet.payload_bytes == bytes.fromhex("02026073")


def test_gateserv_transport_defaults_to_local_1917(monkeypatch) -> None:
    _clear_gate_env(monkeypatch)
    monkeypatch.setenv("GATE_WIEGAND_TRANSPORT", "gateserv_tcp")

    controller = GateController.from_env()

    assert controller.config.transport == "gateserv_tcp"
    assert controller.config.host == "127.0.0.1"
    assert controller.config.port == 1917
    assert controller.config.payload_format == "frame_hex"


def test_dry_run_returns_packet_diagnostics(monkeypatch) -> None:
    _clear_gate_env(monkeypatch)
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("GATE_WIEGAND_TRANSPORT", "gateserv_tcp")

    result = GateController.from_env().open_gate(
        gate_id="main",
        access_point_id=19,
        facility_code=1,
        card_number=12345,
    )

    assert result.success is True
    assert result.details is not None
    assert result.details["transport"] == "gateserv_tcp"
    assert result.details["packet"]["frame_hex"] == "2026073"
    assert result.details["packet"]["payload_hex_be"] == "02026073"


def test_controller_tcp_raw_bytes_send_uses_big_endian_packet(monkeypatch) -> None:
    _clear_gate_env(monkeypatch)
    monkeypatch.setenv("GATE_WIEGAND_TRANSPORT", "tcp")
    monkeypatch.setenv("GATE_WIEGAND_TCP_HOST", "192.168.1.244")
    monkeypatch.setenv("GATE_WIEGAND_TCP_PORT", "5000")
    monkeypatch.setenv("GATE_WIEGAND_TCP_PAYLOAD_FORMAT", "raw_bytes")
    monkeypatch.setenv("GATE_WIEGAND_TCP_APPEND_NEWLINE", "false")

    captured: dict[str, object] = {}

    class _DummyConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def sendall(self, data: bytes) -> None:
            captured["wire_data"] = data

    def _fake_create_connection(address, timeout):
        captured["address"] = address
        captured["timeout"] = timeout
        return _DummyConnection()

    monkeypatch.setattr("backend.app.services.gate_controller.socket.create_connection", _fake_create_connection)

    result = GateController.from_env().open_gate(
        gate_id="entry",
        access_point_id=19,
        facility_code=1,
        card_number=12345,
    )

    assert result.success is True
    assert captured["address"] == ("192.168.1.244", 5000)
    assert captured["wire_data"] == bytes.fromhex("02026073")
    assert result.details is not None
    assert result.details["wire"]["mode"] == "raw_bytes"
    assert result.details["wire"]["hex"] == "02026073"


def test_connectivity_check_uses_connect_ex(monkeypatch) -> None:
    _clear_gate_env(monkeypatch)
    captured: dict[str, object] = {}

    class _DummySocket:
        def settimeout(self, timeout: float) -> None:
            captured["timeout"] = timeout

        def connect_ex(self, address) -> int:
            captured["address"] = address
            return 0

        def close(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr("backend.app.services.gate_controller.socket.socket", lambda *args, **kwargs: _DummySocket())

    result = GateController.from_env().check_connectivity("127.0.0.1", 1917, timeout=1.5)

    assert result["reachable"] is True
    assert result["error"] is None
    assert captured["address"] == ("127.0.0.1", 1917)
    assert captured["timeout"] == 1.5
    assert captured["closed"] is True
