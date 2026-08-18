"""Interactive Command Line Interface for FRIDAY."""

import sys
from friday.agent.agent import FridayAgent
from friday.core.config import get_settings
from friday.core.logging import get_logger, setup_logging

logger = get_logger("cli")

BANNER = r"""
========================================================================
  ______ _____  _____ _____             __     __
 |  ____|  __ \|_   _|  __ \   /\ \ \   \ \   / /
 | |__  | |__) | | | | |  | | /  \ \ \   \ \_/ / 
 |  __| |  _  /  | | | |  | |/ /\ \ \ \   \   /  
 | |    | | \ \ _| |_| |__| / ____ \ \ \   | |   
 |_|    |_|  \_\_____|_____/_/    \_\ \_\  |_|   
  Fully Responsive Intelligent Digital Assistant for You
  Version 0.1.0 — Core Foundation
========================================================================
Type your message to begin, or use a command:
  /help    - Show available commands
  /status  - Inspect agent status & configuration
  /history - Display current conversation memory
  /tools   - List registered tools & safety tiers
  /clear   - Clear conversation history
  /exit    - Gracefully shutdown FRIDAY
========================================================================
"""


def print_help() -> None:
    print("\n--- Available CLI Commands ---")
    print("  /help    : Show this help menu")
    print("  /status  : Display active model, memory stats, and tools")
    print("  /history : View stored conversation turns")
    print("  /tools   : View loaded tools and safety classifications")
    print("  /clear   : Reset conversation memory buffer")
    print("  /exit    : Exit FRIDAY assistant (or /quit)")
    print("------------------------------\n")


def print_status(agent: FridayAgent) -> None:
    status = agent.get_status()
    print("\n--- Agent Status ---")
    print(f"  Agent Name      : {status['agent_name']}")
    print(f"  User Address    : {status['user_name']}")
    print(f"  LLM Provider    : {status['provider']}")
    print(f"  Model           : {status['model']}")
    print(f"  Memory Usage    : {status['memory_messages']} / {status['memory_capacity']} messages")
    print(f"  Loaded Tools    : {len(status['tools_registered'])}")
    for t in status["tools_registered"]:
        print(f"    * {t}")
    print("--------------------\n")


def print_history(agent: FridayAgent) -> None:
    history = agent.get_history()
    print(f"\n--- Conversation History ({len(history)} messages) ---")
    if not history:
        print("  (Memory buffer is empty)")
    else:
        for idx, msg in enumerate(history, 1):
            time_str = msg.timestamp.strftime("%H:%M:%S")
            print(f"  [{idx}] [{time_str}] {msg.role.value.upper()}: {msg.content}")
    print("----------------------------------------------------\n")


def print_tools(agent: FridayAgent) -> None:
    tools = agent.tools.list_tools()
    print(f"\n--- Registered Tools ({len(tools)}) ---")
    if not tools:
        print("  (No tools registered)")
    else:
        for tool in tools:
            print(f"  * {tool.name} [{tool.safety_level.value}]")
            print(f"    Description : {tool.description}")
            print(f"    Parameters  : {list(tool.parameters.get('properties', {}).keys())}")
    print("---------------------------------------\n")


def on_tool_event(tool_call, tool_result) -> None:
    """Print clean indicator in console when a tool executes."""
    status_tag = "[ERROR]" if tool_result.is_error else "[DONE]"
    print(f"  -> [Tool] {tool_call.name} ({tool_result.safety_level.value}) {status_tag}")


def main() -> None:
    """Main CLI entry point."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    from pydantic import ValidationError
    try:
        settings = get_settings()
    except ValidationError as e:
        print(f"\n[Configuration Error]: Failed to validate application configuration.")
        print(f"Details: {e}\n")
        sys.exit(1)

    setup_logging(level=settings.log_level, log_file=settings.log_file)
    logger.info("Starting FRIDAY CLI session")

    agent = FridayAgent(settings=settings, tool_callback=on_tool_event)

    print(BANNER)
    print(f"FRIDAY initialized. Provider: [{agent.llm.provider_name}], Model: [{agent.llm.model}].\n")

    while True:
        try:
            user_input = input(f"{settings.user_name} > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nShutting down FRIDAY. Good day, Boss.")
            break

        if not user_input:
            continue

        cmd = user_input.lower()
        if cmd in ("/exit", "/quit", "exit", "quit"):
            print("Shutting down FRIDAY. Goodbye!")
            break
        elif cmd == "/help":
            print_help()
            continue
        elif cmd == "/status":
            print_status(agent)
            continue
        elif cmd == "/history":
            print_history(agent)
            continue
        elif cmd == "/tools":
            print_tools(agent)
            continue
        elif cmd == "/clear":
            agent.clear_memory()
            print("Conversation memory cleared.")
            continue

        # Process standard conversation turn
        try:
            response = agent.process_message(user_input)
            print(f"\n{settings.agent_name} > {response.content}\n")
        except Exception as e:
            print(f"\n[Error]: {e}\n")


if __name__ == "__main__":
    main()
