from __future__ import annotations

from backend.app.services.gate_controller import GateController


def encode_wiegand26(facility_code: int, card_number: int) -> bytes:
    packet = GateController.build_wiegand26_packet(facility_code=facility_code, card_number=card_number)
    print(f"Facility: {facility_code}, Card: {card_number}")
    print(f"Wiegand 26 bits: {packet.bits}")
    print(f"Frame hex (26-bit): {packet.frame_hex}")
    print(f"Packet bytes: {packet.payload_hex_be}")
    print(f"Packet decimal: {list(packet.payload_bytes)}")
    return packet.payload_bytes


if __name__ == "__main__":
    encode_wiegand26(facility_code=1, card_number=12345)
    print("Packet prepared successfully (not sent)")
