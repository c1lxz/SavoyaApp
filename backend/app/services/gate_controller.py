from __future__ import annotations

import json
import logging
import os
import socket
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

WIEGAND_BITS = 26
_DRY_RUN_VALUES = {"", "dry_run", "mock", "simulate", "disabled"}
_TCP_VALUES = {"tcp", "tcp_ip", "socket", "controller_tcp"}
_GATESERV_VALUES = {"gateserv", "gateserv_tcp", "gate_server"}


def _env(name: str, *aliases: str, default: str | None = None, allow_empty: bool = False) -> str | None:
    for key in (name, *aliases):
        if key not in os.environ:
            continue
        value = os.environ[key]
        if value or allow_empty:
            return value
    return default


def _env_bool(name: str, *aliases: str, default: bool = False) -> bool:
    raw = _env(name, *aliases)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(raw: str | None, *, field_name: str) -> int | None:
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning("Invalid integer env value for %s: %s", field_name, raw)
        return None


@dataclass(frozen=True)
class Wiegand26Packet:
    facility_code: int
    card_number: int
    bit_length: int
    bits: str
    frame: int
    frame_hex: str
    payload_bytes: bytes
    payload_hex_be: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "bit_length": self.bit_length,
            "facility_code": self.facility_code,
            "card_number": self.card_number,
            "bits": self.bits,
            "frame": self.frame,
            "frame_hex": self.frame_hex,
            # Backward-compatible alias for the previous 7-char hex field.
            "payload_hex": self.frame_hex,
            "payload_hex_be": self.payload_hex_be,
        }


@dataclass(frozen=True)
class GateTransportConfig:
    transport: str
    dry_run: bool
    timeout_seconds: float
    host: str | None = None
    port: int | None = None
    payload_format: str = "frame_hex"
    append_newline: bool = True
    encoding: str = "utf-8"
    url: str | None = None
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "transport": self.transport,
            "dry_run": self.dry_run,
            "timeout_seconds": self.timeout_seconds,
            "host": self.host,
            "port": self.port,
            "payload_format": self.payload_format,
            "append_newline": self.append_newline,
            "encoding": self.encoding,
            "url": self.url,
            "note": self.note,
        }


@dataclass(frozen=True)
class GateSendResult:
    success: bool
    message: str
    error_code: str | None = None
    details: dict[str, Any] | None = None


class GateController:
    def __init__(self, config: GateTransportConfig) -> None:
        self.config = config

    @classmethod
    def from_env(cls) -> GateController:
        raw_transport = (_env("GATE_WIEGAND_TRANSPORT", default="dry_run") or "dry_run").strip().lower()
        transport = raw_transport or "dry_run"
        timeout_raw = _env("GATE_WIEGAND_TIMEOUT_SECONDS", default="2.0") or "2.0"
        timeout_seconds = float(timeout_raw)
        dry_run = _env_bool("DRY_RUN", "GATE_DRY_RUN", "GATE_WIEGAND_DRY_RUN", default=transport in _DRY_RUN_VALUES)

        if transport in _DRY_RUN_VALUES:
            return cls(
                GateTransportConfig(
                    transport="dry_run",
                    dry_run=True,
                    timeout_seconds=timeout_seconds,
                    payload_format="frame_hex",
                    append_newline=False,
                    encoding="utf-8",
                )
            )

        if transport in _GATESERV_VALUES:
            host = (_env("GATE_GATESERV_HOST", "GATE_WIEGAND_GATESERV_HOST", default="127.0.0.1") or "").strip()
            port = _parse_int(
                _env("GATE_GATESERV_PORT", "GATE_WIEGAND_GATESERV_PORT", default="1917"),
                field_name="GATE_GATESERV_PORT",
            )
            payload_format = (
                _env(
                    "GATE_GATESERV_PAYLOAD_FORMAT",
                    "GATE_WIEGAND_GATESERV_PAYLOAD_FORMAT",
                    default="frame_hex",
                )
                or "frame_hex"
            ).strip().lower()
            return cls(
                GateTransportConfig(
                    transport="gateserv_tcp",
                    dry_run=dry_run,
                    timeout_seconds=timeout_seconds,
                    host=host or None,
                    port=port,
                    payload_format=payload_format,
                    append_newline=_env_bool(
                        "GATE_GATESERV_APPEND_NEWLINE",
                        "GATE_WIEGAND_GATESERV_APPEND_NEWLINE",
                        default=True,
                    ),
                    encoding=(_env("GATE_GATESERV_ENCODING", "GATE_WIEGAND_GATESERV_ENCODING", default="utf-8") or "utf-8").strip(),
                    note=(
                        "GateServ TCP/1917 is confirmed on the real server and documented by the vendor as a "
                        "Gate-Monitoring port; the open-command payload format is still a hypothesis."
                    ),
                )
            )

        if transport in _TCP_VALUES:
            host = (_env("GATE_WIEGAND_TCP_HOST", "GATE_CONTROLLER_HOST") or "").strip()
            port = _parse_int(
                _env("GATE_WIEGAND_TCP_PORT", "GATE_CONTROLLER_PORT"),
                field_name="GATE_WIEGAND_TCP_PORT",
            )
            payload_format = (_env("GATE_WIEGAND_TCP_PAYLOAD_FORMAT", default="json") or "json").strip().lower()
            return cls(
                GateTransportConfig(
                    transport="controller_tcp",
                    dry_run=dry_run,
                    timeout_seconds=timeout_seconds,
                    host=host or None,
                    port=port,
                    payload_format=payload_format,
                    append_newline=_env_bool("GATE_WIEGAND_TCP_APPEND_NEWLINE", default=True),
                    encoding=(_env("GATE_WIEGAND_TCP_ENCODING", default="utf-8") or "utf-8").strip(),
                    note="Direct controller TCP remains a fallback path. The real production topology is not fully confirmed yet.",
                )
            )

        if transport == "http":
            return cls(
                GateTransportConfig(
                    transport="http",
                    dry_run=dry_run,
                    timeout_seconds=timeout_seconds,
                    url=(_env("GATE_WIEGAND_HTTP_URL") or "").strip() or None,
                    note="HTTP transport is application-defined and must match the deployed gate bridge/API.",
                )
            )

        return cls(
            GateTransportConfig(
                transport=transport,
                dry_run=dry_run,
                timeout_seconds=timeout_seconds,
                note="Unknown transport configured.",
            )
        )

    @staticmethod
    def build_wiegand26_packet(facility_code: int, card_number: int) -> Wiegand26Packet:
        if not (0 <= facility_code <= 255):
            raise ValueError("facility_code must be in [0, 255]")
        if not (0 <= card_number <= 65535):
            raise ValueError("card_number must be in [0, 65535]")

        data24 = (facility_code << 16) | card_number
        high12 = (data24 >> 12) & 0xFFF
        low12 = data24 & 0xFFF

        parity_even = bin(high12).count("1") % 2
        parity_odd = 1 - (bin(low12).count("1") % 2)
        frame26 = (parity_even << 25) | (data24 << 1) | parity_odd
        payload_bytes = frame26.to_bytes(4, byteorder="big")

        return Wiegand26Packet(
            facility_code=facility_code,
            card_number=card_number,
            bit_length=WIEGAND_BITS,
            bits=f"{frame26:026b}",
            frame=frame26,
            frame_hex=f"{frame26:07X}",
            payload_bytes=payload_bytes,
            payload_hex_be=payload_bytes.hex(),
        )

    def check_connectivity(self, host: str, port: int, timeout: float | None = None) -> dict[str, Any]:
        timeout_value = timeout if timeout is not None else self.config.timeout_seconds
        result = {
            "host": host,
            "port": port,
            "reachable": False,
            "latency_ms": None,
            "error": None,
        }
        try:
            started_at = time.perf_counter()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout_value)
            code = sock.connect_ex((host, port))
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
            sock.close()
            if code == 0:
                result["reachable"] = True
                result["latency_ms"] = elapsed_ms
            else:
                result["error"] = f"connect_ex returned {code}"
        except Exception as exc:  # pragma: no cover - exercised by manual utility
            result["error"] = str(exc)
        return result

    def open_gate(
        self,
        *,
        gate_id: str,
        facility_code: int,
        card_number: int,
        access_point_id: int | None = None,
    ) -> GateSendResult:
        return self.send_key(
            facility_code=facility_code,
            card_number=card_number,
            gate_id=gate_id,
            access_point_id=access_point_id,
        )

    def send_key(
        self,
        *,
        facility_code: int,
        card_number: int,
        gate_id: str,
        access_point_id: int | None = None,
    ) -> GateSendResult:
        packet = self.build_wiegand26_packet(facility_code=facility_code, card_number=card_number)
        details = {
            "gate_id": gate_id,
            "access_point_id": access_point_id,
            "transport": self.config.transport,
            "dry_run": self.config.dry_run,
            "packet": packet.as_dict(),
            "transport_config": self.config.as_dict(),
        }

        logger.info(
            "Prepared Wiegand-26 packet transport=%s dry_run=%s gate_id=%s access_point_id=%s frame_hex=%s payload_hex_be=%s",
            self.config.transport,
            self.config.dry_run,
            gate_id,
            access_point_id,
            packet.frame_hex,
            packet.payload_hex_be,
        )
        if self.config.note:
            logger.warning("Gate transport note: %s", self.config.note)

        if self.config.transport == "http":
            return self._send_http(packet=packet, details=details)

        wire = self._build_wire_payload(packet=packet, gate_id=gate_id, access_point_id=access_point_id)
        details.update(wire["details"])

        if self.config.dry_run:
            return GateSendResult(
                success=True,
                message=f"Gate dry-run prepared for {gate_id} via {self.config.transport}",
                details=details,
            )

        if self.config.transport in {"gateserv_tcp", "controller_tcp"}:
            return self._send_tcp(wire_data=wire["wire_data"], details=details)

        return GateSendResult(
            success=False,
            error_code="transport_not_supported",
            message=f"Unknown transport: {self.config.transport}",
            details=details,
        )

    def _build_wire_payload(
        self,
        *,
        packet: Wiegand26Packet,
        gate_id: str,
        access_point_id: int | None,
    ) -> dict[str, Any]:
        payload = {
            "gate_id": gate_id,
            "access_point_id": access_point_id,
            "wiegand": packet.as_dict(),
        }
        payload_format = self.config.payload_format.strip().lower()

        if payload_format == "json":
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            wire_data = (body + ("\n" if self.config.append_newline else "")).encode(self.config.encoding)
            return {
                "wire_data": wire_data,
                "details": {
                    "wire": {
                        "mode": "json",
                        "text": body,
                        "hex": wire_data.hex(),
                        "length": len(wire_data),
                    }
                },
            }

        if payload_format in {"frame_hex", "payload_hex", "hex"}:
            text = packet.frame_hex + ("\n" if self.config.append_newline else "")
            wire_data = text.encode(self.config.encoding)
            return {
                "wire_data": wire_data,
                "details": {
                    "wire": {
                        "mode": "frame_hex",
                        "text": text.rstrip("\n"),
                        "hex": wire_data.hex(),
                        "length": len(wire_data),
                    }
                },
            }

        if payload_format in {"payload_hex_be", "bytes_hex", "hex_be"}:
            text = packet.payload_hex_be + ("\n" if self.config.append_newline else "")
            wire_data = text.encode(self.config.encoding)
            return {
                "wire_data": wire_data,
                "details": {
                    "wire": {
                        "mode": "payload_hex_be",
                        "text": text.rstrip("\n"),
                        "hex": wire_data.hex(),
                        "length": len(wire_data),
                    }
                },
            }

        if payload_format in {"raw_bytes", "bytes", "binary"}:
            return {
                "wire_data": packet.payload_bytes,
                "details": {
                    "wire": {
                        "mode": "raw_bytes",
                        "hex": packet.payload_hex_be,
                        "length": len(packet.payload_bytes),
                    }
                },
            }

        if payload_format in {"fc_cn", "facility_card"}:
            text = f"{packet.facility_code}:{packet.card_number}" + ("\n" if self.config.append_newline else "")
            wire_data = text.encode(self.config.encoding)
            return {
                "wire_data": wire_data,
                "details": {
                    "wire": {
                        "mode": "fc_cn",
                        "text": text.rstrip("\n"),
                        "hex": wire_data.hex(),
                        "length": len(wire_data),
                    }
                },
            }

        raise ValueError(f"Unknown payload format: {payload_format}")

    def _send_tcp(self, *, wire_data: bytes, details: dict[str, Any]) -> GateSendResult:
        host = self.config.host
        port = self.config.port
        if not host:
            return GateSendResult(
                success=False,
                error_code="integration_unavailable",
                message="TCP host is not configured",
                details=details,
            )
        if port is None:
            return GateSendResult(
                success=False,
                error_code="integration_unavailable",
                message="TCP port is not configured",
                details=details,
            )

        try:
            with socket.create_connection((host, port), timeout=self.config.timeout_seconds) as conn:
                conn.sendall(wire_data)
            logger.info("Gate TCP send completed host=%s port=%s bytes=%s", host, port, len(wire_data))
            return GateSendResult(
                success=True,
                message=f"Gate command sent via {self.config.transport} to {host}:{port}. Physical opening is not confirmed.",
                details=details,
            )
        except Exception as exc:
            logger.exception("Gate TCP send failed host=%s port=%s", host, port)
            return GateSendResult(
                success=False,
                error_code="transport_error",
                message=f"Gate TCP transport failed: {exc}",
                details={**details, "transport_error": str(exc)},
            )

    def _send_http(self, *, packet: Wiegand26Packet, details: dict[str, Any]) -> GateSendResult:
        url = self.config.url
        payload = {
            "gate_id": details["gate_id"],
            "access_point_id": details["access_point_id"],
            "wiegand": packet.as_dict(),
        }
        details["wire"] = {"mode": "http_json", "payload": payload}

        if self.config.dry_run:
            return GateSendResult(
                success=True,
                message=f"Gate dry-run prepared for {details['gate_id']} via http",
                details=details,
            )

        if not url:
            return GateSendResult(
                success=False,
                error_code="integration_unavailable",
                message="GATE_WIEGAND_HTTP_URL is not configured",
                details=details,
            )

        headers: dict[str, str] = {"Content-Type": "application/json"}
        token = (_env("GATE_WIEGAND_HTTP_TOKEN") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            import httpx
        except ImportError:
            return GateSendResult(
                success=False,
                error_code="integration_unavailable",
                message="httpx is not installed for HTTP transport",
                details=details,
            )

        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=self.config.timeout_seconds)
            if response.status_code >= 400:
                return GateSendResult(
                    success=False,
                    error_code="transport_http_error",
                    message=f"Gate HTTP transport returned {response.status_code}",
                    details={**details, "http_status_code": response.status_code},
                )

            try:
                response_payload = response.json()
            except ValueError:
                response_payload = {}

            if isinstance(response_payload, dict):
                return GateSendResult(
                    success=bool(response_payload.get("success", True)),
                    message=str(response_payload.get("message") or "Gate HTTP transport accepted the command"),
                    error_code=str(response_payload.get("error_code")) if response_payload.get("error_code") else None,
                    details={**details, "http_response": response_payload},
                )

            return GateSendResult(
                success=True,
                message="Gate HTTP transport accepted the command",
                details=details,
            )
        except Exception as exc:
            logger.exception("Gate HTTP send failed url=%s", url)
            return GateSendResult(
                success=False,
                error_code="transport_error",
                message=f"Gate HTTP transport failed: {exc}",
                details={**details, "transport_error": str(exc)},
            )
