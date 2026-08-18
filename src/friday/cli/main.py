"""Interactive Command Line Interface for FRIDAY."""

import sys
from friday.agent.agent import FridayAgent
from friday.cli.auth import CLIAuthorizer
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
  Version 0.4.1 — Persistent Memory
========================================================================
Type your message to begin, or use a command:
  /new [title]      - Start a new conversation session
  /conversations    - List stored conversation sessions
  /switch <id>      - Switch to an existing conversation
  /rename <title>   - Rename the active conversation
  /current          - Show active conversation details
  /search <query>   - Search historical conversations for keywords
  /status           - Inspect agent status & configuration
  /history          - Display current conversation memory
  /tools            - List registered tools & safety tiers
  /clear            - Clear messages in active conversation
  /delete [id]      - Delete a conversation (requires confirmation)
  /backup [path]    - Create an online local backup of database
  /export [path]    - Export active conversation to local JSON file
  /purge            - Permanently delete all stored memory (strong confirmation)
  /help             - Show available commands
  /exit             - Gracefully shutdown FRIDAY
========================================================================
"""


def print_help() -> None:
    print("\n--- Available CLI Commands ---")
    print("  /new [title]    : Start a new conversation session")
    print("  /conversations  : List all stored conversation sessions (/list)")
    print("  /switch <id>    : Switch to a conversation by ID or prefix")
    print("  /rename <title> : Rename the current active conversation")
    print("  /current        : Show metadata for the active conversation")
    print("  /search <query> : Search historical conversations for keywords")
    print("  /status         : Display active model, memory stats, and tools")
    print("  /history        : View stored conversation turns")
    print("  /tools          : View loaded tools and safety classifications")
    print("  /clear          : Reset active conversation memory buffer")
    print("  /delete [id]    : Delete a conversation (requires confirmation)")
    print("  /backup [path]  : Create local backup of SQLite database")
    print("  /export [path]  : Export current conversation to JSON")
    print("  /purge          : Permanently delete ALL stored memory (requires confirmation)")
    print("  /help           : Show this help menu")
    print("  /exit           : Exit FRIDAY assistant (or /quit)")
    print("------------------------------\n")


def print_status(agent: FridayAgent) -> None:
    status = agent.get_status()
    print("\n--- Agent Status ---")
    print(f"  Agent Name      : {status['agent_name']}")
    print(f"  User Address    : {status['user_name']}")
    print(f"  LLM Provider    : {status['provider']}")
    print(f"  Model           : {status['model']}")
    print(f"  Memory Backend  : {status.get('memory_backend', 'in_memory')}")
    if "conversation_id" in status:
        print(f"  Conversation ID : {status['conversation_id']}")
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


def print_conversations(agent: FridayAgent) -> None:
    convs = agent.list_conversations()
    print(f"\n--- Stored Conversations ({len(convs)}) ---")
    if not convs:
        print("  (No persistent conversations found)")
    else:
        active_id = agent.conversation_id
        for c in convs:
            marker = "*" if c["id"] == active_id else " "
            print(f" {marker} [{c['id'][:8]}] {c['title']} ({c['message_count']} msgs) - Updated: {c['updated_at'][:19]}")
            if c["id"] == active_id:
                print(f"       -> Full ID: {c['id']}")
    print("------------------------------------------\n")


def print_current_conversation(agent: FridayAgent) -> None:
    curr = agent.get_current_conversation()
    print("\n--- Current Active Conversation ---")
    if not curr:
        print(f"  Session ID : {agent.conversation_id or 'In-Memory (Ephemeral)'}")
        print(f"  Messages   : {len(agent.get_history())}")
    else:
        print(f"  ID           : {curr['id']}")
        print(f"  Title        : {curr['title']}")
        print(f"  Created At   : {curr['created_at']}")
        print(f"  Updated At   : {curr['updated_at']}")
        print(f"  Message Count: {curr['message_count']}")
    print("------------------------------------\n")


def print_search_results(agent: FridayAgent, query: str) -> None:
    results = agent.search_memory(query=query, limit=10)
    print(f"\n--- Search Results for '{query}' ({len(results)} matches) ---")
    if not results:
        print("  (No matching messages found in conversation history)")
    else:
        for idx, r in enumerate(results, 1):
            time_str = r.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            print(f"  [{idx}] [{r.conversation_title}] ({time_str}) {r.role.value.upper()}:")
            print(f"      {r.content}")
    print("----------------------------------------------------------\n")


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

    agent = FridayAgent(
        settings=settings,
        tool_callback=on_tool_event,
        authorizer=CLIAuthorizer(),
    )

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
        elif cmd.startswith("/new"):
            parts = user_input.split(maxsplit=1)
            title = parts[1].strip() if len(parts) > 1 else None
            conv_id = agent.create_new_conversation(title=title)
            print(f"\nStarted new conversation: '{title or 'Default Conversation'}' (ID: {conv_id})\n")
            continue
        elif cmd in ("/conversations", "/list"):
            print_conversations(agent)
            continue
        elif cmd.startswith("/switch"):
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2:
                print("\n[Usage]: /switch <conversation_id>\n")
                continue
            target_id = parts[1].strip()
            convs = agent.list_conversations()
            matched = [c for c in convs if c["id"].startswith(target_id)]
            if not matched:
                print(f"\n[Error]: No conversation found matching '{target_id}'.\n")
            elif len(matched) > 1:
                print(f"\n[Error]: Multiple conversations match prefix '{target_id}'. Please provide full ID.\n")
            else:
                agent.switch_conversation(matched[0]["id"])
                print(f"\nSwitched to conversation: '{matched[0]['title']}' (ID: {matched[0]['id']})\n")
            continue
        elif cmd.startswith("/rename"):
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2:
                print("\n[Usage]: /rename <new_title>\n")
                continue
            new_title = parts[1].strip()
            ok = agent.rename_conversation(new_title)
            if ok:
                print(f"\nRenamed active conversation to: '{new_title}'\n")
            else:
                print("\n[Error]: Failed to rename conversation.\n")
            continue
        elif cmd == "/current":
            print_current_conversation(agent)
            continue
        elif cmd.startswith("/search"):
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2:
                print("\n[Usage]: /search <query>\n")
                continue
            search_query = parts[1].strip()
            print_search_results(agent, search_query)
            continue
        elif cmd.startswith("/delete"):
            parts = user_input.split(maxsplit=1)
            target_id = parts[1].strip() if len(parts) > 1 else agent.conversation_id
            if not target_id:
                print("\n[Error]: No conversation to delete.\n")
                continue

            convs = agent.list_conversations()
            matched = [c for c in convs if c["id"].startswith(target_id)]
            if not matched:
                print(f"\n[Error]: No conversation found matching '{target_id}'.\n")
                continue

            target_conv = matched[0]
            confirm = input(f"Are you sure you want to permanently delete conversation '{target_conv['title']}' ({target_conv['id']})? [y/N]: ").strip().lower()
            if confirm in ("y", "yes"):
                agent.delete_conversation(target_conv["id"])
                print(f"\nDeleted conversation '{target_conv['title']}'.\n")
            else:
                print("\nDeletion cancelled.\n")
            continue
        elif cmd == "/clear":
            agent.clear_memory()
            print("Active conversation memory cleared.")
            continue
        elif cmd in ("/purge", "/delete-all", "/clear-all"):
            print("\n[WARNING]: This operation is DESTRUCTIVE and will permanently delete ALL stored conversations and history.")
            confirm = input("To proceed, type 'CONFIRM PURGE': ").strip()
            if confirm == "CONFIRM PURGE":
                count = agent.purge_all_memory()
                print(f"\nAll persistent memory has been completely purged ({count} conversation(s) deleted).\n")
            else:
                print("\nPurge operation cancelled.\n")
            continue
        elif cmd.startswith("/backup"):
            parts = user_input.split(maxsplit=1)
            target = parts[1].strip() if len(parts) > 1 else f"data/backups/friday_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            try:
                out_path = agent.backup_database(target)
                print(f"\nDatabase backup successfully created at '{out_path}'.\n")
            except Exception as e:
                print(f"\n[Error creating backup]: {e}\n")
            continue
        elif cmd.startswith("/export"):
            parts = user_input.split(maxsplit=1)
            target = parts[1].strip() if len(parts) > 1 else f"data/exports/conversation_{agent.conversation_id[:8] if agent.conversation_id else 'export'}.json"
            try:
                data = agent.export_conversation()
                out_path = Path(target).resolve()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                print(f"\nExported active conversation to '{out_path}'.\n")
            except Exception as e:
                print(f"\n[Error exporting conversation]: {e}\n")
            continue

        # Process standard conversation turn
        try:
            response = agent.process_message(user_input)
            print(f"\n{settings.agent_name} > {response.content}\n")
        except Exception as e:
            print(f"\n[Error]: {e}\n")


if __name__ == "__main__":
    main()
