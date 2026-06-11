"""LangChain tools for interacting with ICSSIM PLC tags."""

from langchain.tools import tool

from icssim_client import TAG_LIST, get_all_tags, ics_read, ics_write


@tool(parse_docstring=True)
def read_tag(tag: str) -> str:
    """Read the current value of a single ICSSIM tag.

    Args:
        tag: Name of the tag to read.

    Returns:
        A string containing the tag name and value, or an error message if the
        tag is unknown or the read fails.
    """
    if tag not in TAG_LIST:
        return f"ERROR: Unknown tag '{tag}'. Use list_all_tags to see available tags."

    value = ics_read(tag)
    if value is None:
        return f"ERROR: Failed to read tag '{tag}'."
    return f"{tag} = {value}"


@tool(parse_docstring=True)
def read_all_tags() -> str:
    """Read the current values of all ICSSIM tags.

    Returns:
        A formatted multi-line string listing every tag and its current value.
    """
    values = get_all_tags()
    lines = ["Current ICSSIM tag values:"]
    for tag_name in TAG_LIST:
        lines.append(f"- {tag_name}: {values.get(tag_name)}")
    return "\n".join(lines)


@tool(parse_docstring=True)
def set_actuator_mode(tag: str, mode: int) -> str:
    """Set the operating mode of a valve or actuator.

    Args:
        tag: Mode tag to update. Valid tags are tank_input_valve_mode,
            tank_output_valve_mode, and conveyor_belt_engine_mode.
        mode: Operating mode. Use 1 for Force OFF, 2 for Force ON, or 3 for
            Auto PLC-controlled mode.

    Returns:
        OK if the write succeeds, or an error message if the tag, mode, or
        Modbus write fails.
    """
    valid_tags = {
        "tank_input_valve_mode",
        "tank_output_valve_mode",
        "conveyor_belt_engine_mode",
    }
    if tag not in valid_tags:
        return (
            "ERROR: Invalid actuator mode tag. Valid tags are "
            "tank_input_valve_mode, tank_output_valve_mode, "
            "conveyor_belt_engine_mode."
        )
    if mode not in {1, 2, 3}:
        return "ERROR: Invalid mode. Use 1 = Force OFF, 2 = Force ON, or 3 = Auto."

    try:
        success = ics_write(tag, float(mode))
    except Exception as exc:
        return f"ERROR: Failed to set actuator mode: {exc}"

    if not success:
        return f"ERROR: Modbus write failed for tag '{tag}'."
    return "OK"


@tool(parse_docstring=True)
def set_level_threshold(tag: str, value: float) -> str:
    """Update a tank level threshold setpoint.

    Args:
        tag: Threshold tag to update. Valid tags are tank_level_min and
            tank_level_max.
        value: New threshold value to write.

    Returns:
        OK if the write succeeds, or an error message if the tag or Modbus
        write fails.
    """
    valid_tags = {"tank_level_min", "tank_level_max"}
    if tag not in valid_tags:
        return "ERROR: Invalid threshold tag. Valid tags are tank_level_min and tank_level_max."

    try:
        success = ics_write(tag, value)
    except Exception as exc:
        return f"ERROR: Failed to set level threshold: {exc}"

    if not success:
        return f"ERROR: Modbus write failed for tag '{tag}'."
    return "OK"


@tool(parse_docstring=True)
def list_all_tags() -> str:
    """List all available ICSSIM tag names.

    Returns:
        A formatted multi-line string containing every tag name with its PLC
        number and input or output type.
    """
    lines = ["Available ICSSIM tags:"]
    for tag_name, tag_info in TAG_LIST.items():
        lines.append(
            f"- {tag_name}: plc={tag_info['plc']}, type={tag_info['type']}"
        )
    return "\n".join(lines)
