"""Interactive LangGraph agent for supervising ICSSIM."""

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

from langchain.agents import create_agent
from langchain.messages import AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from ics_tools import (
    list_all_tags,
    read_all_tags,
    read_tag,
    set_actuator_mode,
    set_level_threshold,
)


SYSTEM_PROMPT = SystemMessage(
    content=(
        "You are an ICS supervisory control agent for a bottle-filling factory "
        "simulation (ICSSIM).\n"
        "You can read sensor values and send control commands to PLCs via the "
        "provided tools.\n"
        "Mode values: 1 = Force OFF, 2 = Force ON, 3 = Auto (PLC-controlled)."
    )
)


def build_agent():
    """Create the ICSSIM supervisory control agent."""
    model = ChatOpenAI(
        model="deepseek-v4-flash",
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
    )
    tools = [
        read_tag,
        read_all_tags,
        set_actuator_mode,
        set_level_threshold,
        list_all_tags,
    ]
    checkpointer = InMemorySaver()
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )


def _chunk_to_text(chunk: AIMessageChunk) -> str:
    """Extract printable text from a streamed model chunk."""
    content = chunk.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "".join(parts)
    return ""


def stream_agent_response(agent, user_input: str, config: dict) -> None:
    """Stream one agent response to stdout as tokens arrive."""
    print("Agent: ", end="", flush=True)
    printed_any_token = False

    for chunk, metadata in agent.stream(
        {"messages": [HumanMessage(content=user_input)]},
        config,
        stream_mode="messages",
    ):
        if isinstance(chunk, ToolMessage):
            continue

        if not isinstance(chunk, AIMessageChunk):
            continue

        tool_call_chunks = getattr(chunk, "tool_call_chunks", None)
        if tool_call_chunks:
            continue

        text = _chunk_to_text(chunk)
        if not text:
            continue

        printed_any_token = True
        print(text, end="", flush=True)

    if not printed_any_token:
        print("(no text response)", end="")
    print()


def main() -> None:
    """Run the interactive operator CLI loop."""
    agent = build_agent()
    config = {"configurable": {"thread_id": "icssim-session-001"}}

    while True:
        try:
            user_input = input("Operator > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if user_input.lower() in {"exit", "quit"}:
            break
        if not user_input:
            continue

        stream_agent_response(agent, user_input, config)


if __name__ == "__main__":
    main()
