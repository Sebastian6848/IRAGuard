"""Modbus TCP client helpers for the ICSSIM bottle-filling simulation."""

from __future__ import annotations

from pyModbusTCP.client import ModbusClient


PLC1_HOST = "127.0.0.1"
PLC1_PORT = 5502
PLC2_HOST = "127.0.0.1"
PLC2_PORT = 5503
WORD_NUM = 2
PRECISION = 4
PRECISION_FACTOR = 10**PRECISION
REGISTER_BASE = 2**16

TAG_LIST = {
    "tank_input_valve_status": {"id": 0, "plc": 1, "type": "output"},
    "tank_input_valve_mode": {"id": 1, "plc": 1, "type": "output"},
    "tank_level_value": {"id": 2, "plc": 1, "type": "input"},
    "tank_level_min": {"id": 3, "plc": 1, "type": "output"},
    "tank_level_max": {"id": 4, "plc": 1, "type": "output"},
    "tank_output_valve_status": {"id": 5, "plc": 1, "type": "output"},
    "tank_output_valve_mode": {"id": 6, "plc": 1, "type": "output"},
    "tank_output_flow_value": {"id": 7, "plc": 1, "type": "input"},
    "conveyor_belt_engine_status": {"id": 8, "plc": 2, "type": "output"},
    "conveyor_belt_engine_mode": {"id": 9, "plc": 2, "type": "output"},
    "bottle_level_value": {"id": 10, "plc": 2, "type": "input"},
    "bottle_level_max": {"id": 11, "plc": 2, "type": "output"},
    "bottle_distance_to_filler_value": {"id": 12, "plc": 2, "type": "input"},
}


_PLC_CLIENTS: dict[int, ModbusClient | None] = {
    1: None,
    2: None,
}


def _get_client(plc: int) -> ModbusClient:
    if plc not in _PLC_CLIENTS:
        raise ValueError(f"Unknown PLC number: {plc}")

    client = _PLC_CLIENTS[plc]
    if client is None:
        if plc == 1:
            client = ModbusClient(
                host=PLC1_HOST,
                port=PLC1_PORT,
                auto_open=True,
                auto_close=False,
            )
        else:
            client = ModbusClient(
                host=PLC2_HOST,
                port=PLC2_PORT,
                auto_open=True,
                auto_close=False,
            )
        _PLC_CLIENTS[plc] = client
    return client


def _get_register_address(tag_id: int) -> int:
    return tag_id * WORD_NUM


def _decode_registers(registers: list[int] | None) -> float | None:
    if registers is None or len(registers) != WORD_NUM:
        return None

    result = 0
    base_holder = 1
    for word in registers:
        result *= base_holder
        result += word
        base_holder *= REGISTER_BASE
    return result / PRECISION_FACTOR


def _encode_registers(value: float) -> list[int]:
    number = int(value * PRECISION_FACTOR)
    max_int = REGISTER_BASE**WORD_NUM
    if number < 0:
        raise ValueError("Negative values are not supported by ICSSIM Modbus encoding")
    if number > max_int:
        raise ValueError("Input number exceeds ICSSIM Modbus register limit")

    registers = []
    while number:
        registers.append(number % REGISTER_BASE)
        number = int(number / REGISTER_BASE)

    while len(registers) < WORD_NUM:
        registers.append(0)

    registers.reverse()
    return registers


def ics_read(tag: str) -> float | None:
    """Read a single ICSSIM holding register value.

    Args:
        tag: Name of the tag to read.

    Returns:
        The register value divided by 100.0, or None if the tag is unknown or
        the Modbus read fails.
    """
    tag_info = TAG_LIST.get(tag)
    if tag_info is None:
        return None

    try:
        client = _get_client(tag_info["plc"])
        regs = client.read_holding_registers(_get_register_address(tag_info["id"]), WORD_NUM)
    except Exception:
        return None

    return _decode_registers(regs)


def ics_write(tag: str, value: float) -> bool:
    """Write a single ICSSIM holding register value.

    Args:
        tag: Name of the tag to write.
        value: Floating-point value to scale by 100 and write.

    Returns:
        True if the Modbus write succeeds, otherwise False.

    Raises:
        ValueError: If the tag is unknown or refers to an input-only value.
    """
    tag_info = TAG_LIST.get(tag)
    if tag_info is None:
        raise ValueError(f"Unknown tag: {tag}")
    if tag_info["type"] == "input":
        raise ValueError(f"Cannot write to input tag: {tag}")

    client = _get_client(tag_info["plc"])
    registers = _encode_registers(value)
    return bool(client.write_multiple_registers(_get_register_address(tag_info["id"]), registers))


def get_all_tags() -> dict[str, float | None]:
    """Read all known ICSSIM tags.

    Returns:
        A dictionary mapping each tag name to its current value, using None for
        tags that cannot be read.
    """
    return {tag_name: ics_read(tag_name) for tag_name in TAG_LIST}
