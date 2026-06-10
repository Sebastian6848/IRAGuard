"""IRA-Guard decision layer for ICSSIM tool calls."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from icssim_client import TAG_LIST, get_all_tags


ALLOW = "ALLOW"
REJECT_INTENT = "REJECT_INTENT"
REJECT_PHYSICAL = "REJECT_PHYSICAL"
REJECT_CUMULATIVE = "REJECT_CUMULATIVE"

READ_ONLY_TOOLS = {"read_tag", "read_all_tags", "list_all_tags"}
WRITE_TOOLS = {"set_actuator_mode", "set_level_threshold"}
ALL_TOOLS = READ_ONLY_TOOLS | WRITE_TOOLS

MODE_TAGS = {
    "tank_input_valve_mode",
    "tank_output_valve_mode",
    "conveyor_belt_engine_mode",
}
THRESHOLD_TAGS = {"tank_level_min", "tank_level_max"}

DELTA_2 = 0.5


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("iraguard")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    log_path = Path(__file__).with_name("iraguard.log")
    handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


LOGGER = _build_logger()


@dataclass
class SystemSnapshot:
    """Current physical snapshot and derived discrete states."""

    tags: dict[str, float]
    q_tank: str
    q_bottle: str


@dataclass
class AuthorizationEnvelope:
    """Task-level authorization envelope for IRA-Guard."""

    allowed_tools: list[str]
    target_tags: list[str]
    value_bounds: dict[str, tuple[float, float]]
    time_window: tuple[float, float]
    cumulative_budget: float


@dataclass
class BudgetAccumulator:
    """Session-level cumulative setpoint-change accumulator."""

    sigma: float = 0.0
    last_values: dict[str, float] = field(default_factory=dict)

    def check(self, tag: str, value: float, snapshot: SystemSnapshot, budget: float) -> tuple[bool, str, float]:
        old_value = self.last_values.get(tag, snapshot.tags[tag])
        delta = abs(value - old_value)
        if self.sigma + delta > budget:
            return (
                False,
                f"REJECT_CUMULATIVE: tag={tag} delta={delta:.4f} "
                f"sigma={self.sigma:.4f} budget={budget:.4f}",
                delta,
            )
        return True, "", delta

    def commit(self, tag: str, value: float, delta: float) -> None:
        self.sigma += delta
        self.last_values[tag] = value


def default_envelope(duration_seconds: float = 24 * 60 * 60) -> AuthorizationEnvelope:
    """Create a permissive default envelope for the current prototype session."""
    now = time.time()
    return AuthorizationEnvelope(
        allowed_tools=sorted(ALL_TOOLS),
        target_tags=list(TAG_LIST.keys()),
        value_bounds={
            "tank_input_valve_mode": (1, 3),
            "tank_output_valve_mode": (1, 3),
            "conveyor_belt_engine_mode": (1, 3),
            "tank_level_min": (0, 10),
            "tank_level_max": (0, 10),
        },
        time_window=(now, now + duration_seconds),
        cumulative_budget=2.0,
    )


def _require_number(tags: dict[str, float | None], tag: str) -> float:
    value = tags.get(tag)
    if value is None:
        raise ValueError(f"OBSERVE_FAILED: missing value for {tag}")
    return float(value)


def observe_state() -> SystemSnapshot:
    """Read ICSSIM tags and derive q_tank and q_bottle."""
    raw_tags = get_all_tags()
    tags = {tag: _require_number(raw_tags, tag) for tag in TAG_LIST}

    tank_level = tags["tank_level_value"]
    tank_min = tags["tank_level_min"]
    tank_max = tags["tank_level_max"]
    conveyor_status = tags["conveyor_belt_engine_status"]
    bottle_distance = tags["bottle_distance_to_filler_value"]
    bottle_level = tags["bottle_level_value"]
    bottle_max = tags["bottle_level_max"]

    if tank_level > 10:
        q_tank = "Overflow"
    elif tank_level < tank_min:
        q_tank = "Low"
    elif tank_level > tank_max:
        q_tank = "High"
    else:
        q_tank = "Normal"

    if bottle_level > bottle_max:
        q_bottle = "Full"
    elif int(conveyor_status) == 1:
        q_bottle = "Moving"
    elif bottle_distance > 1.0:
        q_bottle = "Waiting"
    else:
        q_bottle = "Filling"

    return SystemSnapshot(tags=tags, q_tank=q_tank, q_bottle=q_bottle)


def check_envelope(
    tool_name: str,
    params: dict[str, Any],
    envelope: AuthorizationEnvelope,
) -> tuple[bool, str]:
    """Validate a tool call against the authorization envelope."""
    if tool_name not in envelope.allowed_tools:
        return False, f"tool {tool_name} is not in allowed_tools"

    tag = params.get("tag")
    if tag is not None and tag not in envelope.target_tags:
        return False, f"tag {tag} is not in target_tags"

    value = params.get("value")
    if value is None and "mode" in params:
        value = params["mode"]
    if tag is not None and value is not None and tag in envelope.value_bounds:
        lower, upper = envelope.value_bounds[tag]
        numeric_value = float(value)
        if numeric_value < lower or numeric_value > upper:
            return False, f"value {numeric_value} for {tag} is outside [{lower}, {upper}]"

    now = time.time()
    start, end = envelope.time_window
    if now < start or now > end:
        return False, "current time is outside envelope time_window"

    return True, ""


def _is_unconditionally_safe_shutdown(tool_name: str, params: dict[str, Any]) -> bool:
    """Return True for actuator shutdown commands that do not need observation."""
    return (
        tool_name == "set_actuator_mode"
        and params.get("tag") in MODE_TAGS
        and params.get("mode") == 1
    )


def check_physical_guard(
    tool_name: str,
    params: dict[str, Any],
    snapshot: SystemSnapshot,
) -> tuple[bool, str]:
    """Validate a tool call against the physical guard table."""
    if tool_name in READ_ONLY_TOOLS:
        return True, ""

    tag = params.get("tag")
    mode = params.get("mode")
    value = params.get("value")
    tags = snapshot.tags
    q_tank = snapshot.q_tank
    q_bottle = snapshot.q_bottle

    if tool_name == "set_actuator_mode":
        if tag not in MODE_TAGS:
            return False, f"invalid actuator mode tag {tag}"
        if mode not in {1, 2, 3}:
            return False, f"invalid actuator mode {mode}"

        if tag == "tank_input_valve_mode":
            if mode == 2:
                tank_min = tags["tank_level_min"]
                tank_max = tags["tank_level_max"]
                delta_1 = (tank_max - tank_min) * 0.1
                if q_tank in {"High", "Overflow"}:
                    return False, f"inlet force-on forbidden while q_tank={q_tank}"
                if tags["tank_level_value"] > tank_max - delta_1:
                    return (
                        False,
                        "inlet force-on forbidden because "
                        f"tank_level_value={tags['tank_level_value']:.4f} > "
                        f"tank_level_max-delta1={tank_max - delta_1:.4f}",
                    )
            if mode == 3 and q_tank == "Overflow":
                return False, "inlet Auto forbidden while q_tank=Overflow"

        if tag == "tank_output_valve_mode":
            if mode == 2:
                if q_bottle != "Filling":
                    return False, f"outlet force-on requires q_bottle=Filling, got {q_bottle}"
                if q_tank == "Low":
                    return False, "outlet force-on forbidden while q_tank=Low"
            if mode == 3 and q_tank in {"Overflow", "Low"}:
                return False, f"outlet Auto forbidden while q_tank={q_tank}"

        if tag == "conveyor_belt_engine_mode":
            if mode == 2:
                if tags["tank_output_flow_value"] != 0:
                    return False, "conveyor force-on requires tank_output_flow_value=0"
                if q_bottle == "Filling":
                    return False, "conveyor force-on forbidden while q_bottle=Filling"

    elif tool_name == "set_level_threshold":
        if tag == "tank_level_max":
            if value is None:
                return False, "missing value for tank_level_max"
            numeric_value = float(value)
            if numeric_value > 10 - DELTA_2:
                return False, f"tank_level_max must be <= {10 - DELTA_2}"
            if numeric_value <= tags["tank_level_min"] + DELTA_2:
                return False, f"tank_level_max must be > tank_level_min + {DELTA_2}"
        elif tag == "tank_level_min":
            if value is None:
                return False, "missing value for tank_level_min"
            numeric_value = float(value)
            if numeric_value < DELTA_2:
                return False, f"tank_level_min must be >= {DELTA_2}"
            if numeric_value >= tags["tank_level_max"] - DELTA_2:
                return False, f"tank_level_min must be < tank_level_max - {DELTA_2}"
        else:
            return False, f"invalid threshold tag {tag}"
    else:
        return False, f"unknown guarded tool {tool_name}"

    return True, ""


class IRAGuard:
    """Core IRA-Guard decision engine."""

    def __init__(self, envelope: AuthorizationEnvelope | None = None) -> None:
        self.envelope = envelope or default_envelope()
        self.budget = BudgetAccumulator()
        self.pending_budget_updates: dict[tuple[str, float], float] = {}
        self.last_snapshot: SystemSnapshot | None = None

    def evaluate(self, tool: str, params: dict[str, Any]) -> tuple[str, str]:
        """Evaluate a tool call before execution."""
        envelope_ok, envelope_reason = check_envelope(tool, params, self.envelope)
        if not envelope_ok:
            self._log_decision(tool, params, REJECT_INTENT, envelope_reason)
            return REJECT_INTENT, envelope_reason

        if tool in READ_ONLY_TOOLS:
            self._log_decision(tool, params, ALLOW, "")
            return ALLOW, ""

        try:
            snapshot = observe_state()
        except Exception as exc:
            if _is_unconditionally_safe_shutdown(tool, params):
                reason = (
                    "physical state observation failed, but mode=1 shutdown is "
                    f"fail-safe allowed: {exc}"
                )
                self._log_decision(tool, params, ALLOW, reason)
                return ALLOW, reason

            reason = f"physical state observation failed: {exc}"
            self._log_decision(tool, params, REJECT_PHYSICAL, reason)
            return REJECT_PHYSICAL, reason
        self.last_snapshot = snapshot

        guard_ok, guard_reason = check_physical_guard(tool, params, snapshot)
        if not guard_ok:
            self._log_decision(tool, params, REJECT_PHYSICAL, guard_reason)
            return REJECT_PHYSICAL, guard_reason

        if tool == "set_level_threshold":
            tag = str(params["tag"])
            value = float(params["value"])
            budget_ok, budget_reason, delta = self.budget.check(
                tag, value, snapshot, self.envelope.cumulative_budget
            )
            if not budget_ok:
                self._log_decision(tool, params, REJECT_CUMULATIVE, budget_reason)
                return REJECT_CUMULATIVE, budget_reason
            self.pending_budget_updates[(tag, value)] = delta

        self._log_decision(tool, params, ALLOW, "")
        return ALLOW, ""

    def commit(self, tool: str, params: dict[str, Any]) -> None:
        """Commit side effects after an allowed tool call succeeds."""
        if tool != "set_level_threshold":
            return
        tag = str(params["tag"])
        value = float(params["value"])
        delta = self.pending_budget_updates.pop((tag, value), 0.0)
        self.budget.commit(tag, value, delta)
        LOGGER.info(
            "budget_commit tool=%s tag=%s value=%.4f delta=%.4f sigma=%.4f",
            tool,
            tag,
            value,
            delta,
            self.budget.sigma,
        )

    def _log_decision(self, tool: str, params: dict[str, Any], decision: str, reason: str) -> None:
        q_tank = self.last_snapshot.q_tank if self.last_snapshot else "Unknown"
        q_bottle = self.last_snapshot.q_bottle if self.last_snapshot else "Unknown"
        LOGGER.info(
            "decision=%s reason=%s tool=%s params=%s q_tank=%s q_bottle=%s sigma=%.4f",
            decision,
            reason,
            tool,
            params,
            q_tank,
            q_bottle,
            self.budget.sigma,
        )


GUARD = IRAGuard()


def guard_evaluate(tool: str, params: dict[str, Any]) -> tuple[str, str]:
    """Evaluate a tool call using the process-wide guard instance."""
    return GUARD.evaluate(tool, params)


def guard_commit(tool: str, params: dict[str, Any]) -> None:
    """Commit a successful guarded tool call."""
    GUARD.commit(tool, params)
