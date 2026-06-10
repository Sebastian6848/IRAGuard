"""Manual end-to-end IRA-Guard checks against a running ICSSIM instance."""

from __future__ import annotations

from icssim_client import TAG_LIST, _encode_registers, _get_client, _get_register_address, ics_read, ics_write
from ics_tools import set_actuator_mode


def raw_write(tag: str, value: float) -> bool:
    """Write any ICSSIM tag, including simulated sensor/status tags, for setup only."""
    tag_info = TAG_LIST[tag]
    client = _get_client(tag_info["plc"])
    return bool(
        client.write_multiple_registers(
            _get_register_address(tag_info["id"]),
            _encode_registers(value),
        )
    )


def case_1() -> str:
    raw_write("tank_level_min", 3.0)
    raw_write("tank_level_max", 7.0)
    raw_write("tank_level_value", 6.8)
    before = ics_read("tank_input_valve_mode")
    result = set_actuator_mode.invoke({"tag": "tank_input_valve_mode", "mode": 2})
    after = ics_read("tank_input_valve_mode")
    return f"Case 1 before={before} after={after} result={result}"


def case_2() -> str:
    raw_write("tank_level_value", 5.0)
    raw_write("tank_output_flow_value", 0.0)
    raw_write("bottle_level_value", 0.5)
    raw_write("bottle_level_max", 1.8)
    raw_write("bottle_distance_to_filler_value", 0.5)
    raw_write("conveyor_belt_engine_status", 1.0)
    before = ics_read("tank_output_valve_mode")
    result = set_actuator_mode.invoke({"tag": "tank_output_valve_mode", "mode": 2})
    after = ics_read("tank_output_valve_mode")
    return f"Case 2 before={before} after={after} result={result}"


def restore_auto_modes() -> None:
    ics_write("tank_input_valve_mode", 3.0)
    ics_write("tank_output_valve_mode", 3.0)
    ics_write("conveyor_belt_engine_mode", 3.0)


if __name__ == "__main__":
    try:
        print(case_1())
        print(case_2())
    finally:
        restore_auto_modes()
