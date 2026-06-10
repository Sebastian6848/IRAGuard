"""Local checks for IRA-Guard physical rejection cases."""

from __future__ import annotations

import iraguard
from iraguard import ALLOW, IRAGuard, REJECT_PHYSICAL, SystemSnapshot


def _snapshot(**overrides: float) -> SystemSnapshot:
    tags = {
        "tank_input_valve_status": 0.0,
        "tank_input_valve_mode": 3.0,
        "tank_level_value": 5.0,
        "tank_level_min": 3.0,
        "tank_level_max": 7.0,
        "tank_output_valve_status": 0.0,
        "tank_output_valve_mode": 3.0,
        "tank_output_flow_value": 0.0,
        "conveyor_belt_engine_status": 0.0,
        "conveyor_belt_engine_mode": 3.0,
        "bottle_level_value": 0.5,
        "bottle_level_max": 1.8,
        "bottle_distance_to_filler_value": 0.5,
    }
    tags.update(overrides)

    tank_level = tags["tank_level_value"]
    tank_min = tags["tank_level_min"]
    tank_max = tags["tank_level_max"]
    if tank_level > 10:
        q_tank = "Overflow"
    elif tank_level < tank_min:
        q_tank = "Low"
    elif tank_level > tank_max:
        q_tank = "High"
    else:
        q_tank = "Normal"

    if tags["bottle_level_value"] > tags["bottle_level_max"]:
        q_bottle = "Full"
    elif int(tags["conveyor_belt_engine_status"]) == 1:
        q_bottle = "Moving"
    elif tags["bottle_distance_to_filler_value"] > 1.0:
        q_bottle = "Waiting"
    else:
        q_bottle = "Filling"

    return SystemSnapshot(tags=tags, q_tank=q_tank, q_bottle=q_bottle)


def test_case_1_reject_inlet_near_max() -> None:
    original_observe_state = iraguard.observe_state
    iraguard.observe_state = lambda: _snapshot(tank_level_value=6.8)
    try:
        decision, reason = IRAGuard().evaluate(
            "set_actuator_mode",
            {"tag": "tank_input_valve_mode", "mode": 2},
        )
    finally:
        iraguard.observe_state = original_observe_state

    assert decision == REJECT_PHYSICAL
    assert "tank_level_value" in reason


def test_case_2_reject_outlet_while_moving() -> None:
    original_observe_state = iraguard.observe_state
    iraguard.observe_state = lambda: _snapshot(conveyor_belt_engine_status=1.0)
    try:
        decision, reason = IRAGuard().evaluate(
            "set_actuator_mode",
            {"tag": "tank_output_valve_mode", "mode": 2},
        )
    finally:
        iraguard.observe_state = original_observe_state

    assert decision == REJECT_PHYSICAL
    assert "Moving" in reason


def test_observation_failure_allows_mode_1_shutdown() -> None:
    original_observe_state = iraguard.observe_state
    iraguard.observe_state = lambda: (_ for _ in ()).throw(
        ValueError("OBSERVE_FAILED: missing value for tank_input_valve_status")
    )
    try:
        decision, reason = IRAGuard().evaluate(
            "set_actuator_mode",
            {"tag": "tank_output_valve_mode", "mode": 1},
        )
    finally:
        iraguard.observe_state = original_observe_state

    assert decision == ALLOW
    assert "fail-safe allowed" in reason


def test_observation_failure_rejects_mode_2_open() -> None:
    original_observe_state = iraguard.observe_state
    iraguard.observe_state = lambda: (_ for _ in ()).throw(
        ValueError("OBSERVE_FAILED: missing value for tank_input_valve_status")
    )
    try:
        decision, reason = IRAGuard().evaluate(
            "set_actuator_mode",
            {"tag": "tank_input_valve_mode", "mode": 2},
        )
    finally:
        iraguard.observe_state = original_observe_state

    assert decision == REJECT_PHYSICAL
    assert "physical state observation failed" in reason


if __name__ == "__main__":
    test_case_1_reject_inlet_near_max()
    test_case_2_reject_outlet_while_moving()
    test_observation_failure_allows_mode_1_shutdown()
    test_observation_failure_rejects_mode_2_open()
    print("IRA-Guard checks passed")
