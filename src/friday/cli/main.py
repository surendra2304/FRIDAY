import argparse
import json
import logging
import sys
import warnings
from datetime import datetime
from pathlib import Path

# The google-genai SDK emits a noisy UserWarning on every direct generate_content
# call; FRIDAY intentionally calls Models.generate_content (no chat wrapper).
warnings.filterwarnings("ignore", message=".*automatic function calling.*")

from friday.agent.agent import FridayAgent
from friday.cli.auth import CLIAuthorizer
from friday.core.config import get_settings
from friday.core.logging import get_logger, setup_logging

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    _console = Console()
except ImportError:  # pragma: no cover - rich is a hard dependency
    _console = None

import shutil

logger = get_logger("cli")

FRIDAY_LOGO_LINES = [
    r"______ _____  _____ ______   ___  __   __",
    r"|  ___| ___ \|_   _||  _  \ / _ \ \ \ / /",
    r"| |_  | |_/ /  | |  | | | |/ /_\ \ \ V / ",
    r"|  _| |    /   | |  | | | ||  _  |  \ /  ",
    r"| |   | |\ \  _| |_ | |/ / | | | |  | |  ",
    r"\_|   \_| \_| \___/ |___/  \_| |_/  \_/  ",
]


def render_friday_banner(version: str = "0.4.6") -> str:
    """Render a cleanly centered, cohesive block-letter FRIDAY startup banner."""
    terminal_width = shutil.get_terminal_size((80, 20)).columns
    # Ensure minimum width so the 41-char logo is never clipped
    width = max(terminal_width, 60)

    lines = [""]
    for logo_line in FRIDAY_LOGO_LINES:
        lines.append(logo_line.center(width))
    lines.append("")
    lines.append("Fully Responsive Intelligent Digital Assistant for You".center(width))
    lines.append("")
    lines.append(f"Version {version}".center(width))
    lines.append("")

    return "\n".join(lines)


# Retain BANNER variable for backwards compatibility
BANNER = render_friday_banner("0.4.6")


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
    print("\n==================================================")
    print("               FRIDAY AGENT STATUS                ")
    print("==================================================")
    print(f"  Agent Name      : {status['agent_name']}")
    print(f"  User Address    : {status['user_name']}")
    print(f"  LLM Provider    : {status['provider']}")
    print(f"  Model           : {status['model']}")
    print(f"  Active Project  : {status.get('active_project', 'PRIMARY')}")
    print("--------------------------------------------------")
    print(f"  Embedding       : {status.get('embedding_provider', 'none')} ({status.get('embedding_model', 'none')})")
    print(f"  Embedding Status: {status.get('embedding_status', 'AVAILABLE')}")
    print(f"  Memory Backend  : {status.get('memory_backend', 'in_memory')}")
    if "conversation_id" in status:
        print(f"  Conversation ID : {status['conversation_id']}")
    print(f"  Memory Usage    : {status['memory_messages']} / {status['memory_capacity']} messages")
    print("--------------------------------------------------")
    print(f"  Loaded Tools    : {len(status['tools_registered'])}")
    for t in status["tools_registered"]:
        print(f"    * {t}")
    print("==================================================\n")



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

    from friday.observability.timeline import global_timeline
    print(global_timeline.format_replay(limit=15) + "\n")


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


def print_action_audit(agent: FridayAgent) -> None:
    """Print a non-destructive audit of FRIDAY's registered action surface."""
    tools = agent.tools.list_tools()
    print("\n==================================================")
    print("              FRIDAY ACTION AUDIT                 ")
    print("==================================================")
    print(f"  Registered Tools : {len(tools)}")
    invalid = []
    for tool in tools:
        params = tool.parameters if isinstance(tool.parameters, dict) else {}
        required = params.get("required", [])
        properties = params.get("properties", {})
        missing_required = [name for name in required if name not in properties]
        if missing_required or not getattr(tool, "name", "") or not getattr(tool, "description", ""):
            invalid.append((tool.name, missing_required))
        print(f"  * {tool.name:<28} [{tool.safety_level.value}]")
    print("--------------------------------------------------")
    print("  Deterministic Voice/Desktop Fast Paths:")
    print("  * open_notepad_and_type")
    print("  * chrome_search")
    print("  * close_chrome")
    print("  * open_settings")
    print("  * open_windows_update")
    print("  * local_time")
    print("  * laptop_specs")
    print("--------------------------------------------------")
    if invalid:
        print("  Audit Result     : FAILED")
        for name, missing in invalid:
            print(f"    - {name}: missing schema entries {missing}")
    else:
        print("  Audit Result     : PASS (metadata/schema smoke check)")
    print("==================================================\n")


from friday.observability.timeline import global_timeline

_active_status = {"obj": None}


def render_status_panel() -> Panel:
    """Generate the live futuristic Status Panel showing cognitive phase, agent, provider, tool, and latency."""
    st = global_timeline.get_status()
    phase = st.get("cognitive_phase", "IDLE")
    agent_name = st.get("active_agent", "General")
    provider = st.get("selected_provider", "Default")
    tool = st.get("active_tool", "None")
    latency = st.get("last_latency_ms", 0.0)

    content = Text()
    content.append("🧠 Cognitive: ", style="bold cyan")
    content.append(f"{phase:<10} ", style="bold green")
    content.append("🤖 Agent: ", style="bold cyan")
    content.append(f"{agent_name:<10} ", style="bold yellow")
    content.append("⚡ Provider: ", style="bold cyan")
    content.append(f"{provider:<10} ", style="bold magenta")
    content.append("🔧 Tool: ", style="bold cyan")
    content.append(f"{tool:<16} ", style="bold blue")
    content.append("⏱ Latency: ", style="bold cyan")
    content.append(f"{latency:>6.1f}ms", style="bold green")

    return Panel(content, title="[bold white]FRIDAY Live Telemetry & Status[/]", border_style="blue", padding=(0, 1))


def on_tool_event(tool_call, tool_result) -> None:
    """Update timeline and Rich spinner while a tool executes."""
    tool_name = getattr(tool_call, "name", "unknown")
    global_timeline.update_status(active_tool=tool_name)
    global_timeline.record_event(
        event_type="tool_execution",
        description=f"Executed tool '{tool_name}'",
        details={"parameters": getattr(tool_call, "parameters", {})},
    )
    status = _active_status.get("obj")
    if status is not None and tool_name:
        try:
            status.update(f"[magenta]Executing Tool: {tool_name}...")
        except Exception:
            pass


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="FRIDAY - Fully Responsive Intelligent Digital Assistant for You",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  python -m friday           Start in default interactive text conversation mode
  python -m friday --voice   Start direct Gemini Live real-time bidirectional voice mode
  python -m friday --doctor  Run system diagnostics and exit
  python -m friday --action-audit
                             List and validate registered safe action surface
  python -m friday --text    Start explicitly in interactive text conversation mode
  python -m friday --debug   Enable verbose diagnostic logs in the console
""",
    )
    parser.add_argument("--voice", action="store_true", help="Start in real-time Gemini Live bidirectional voice mode")
    parser.add_argument("--doctor", action="store_true", help="Run FRIDAY system diagnostics and exit")
    parser.add_argument("--action-audit", action="store_true", help="List and validate FRIDAY's registered action surface")
    parser.add_argument("--enroll-voice", action="store_true", help="Record 5 seconds of speech to enroll your voice profile for speaker recognition")
    parser.add_argument("--run-lab", action="store_true", help="Run FRIDAY Lab multi-provider benchmark suite and print comparison")
    parser.add_argument("--text", action="store_true", help="Start explicitly in interactive text conversation mode")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging in terminal console")
    args, unknown = parser.parse_known_args()

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

    if args.run_lab:
        from friday.lab.experiment import run_standard_lab_suite
        from friday.memory.sqlite import SQLiteConversationMemory
        print("\n==================================================")
        print("  🔬 FRIDAY LAB: Multi-Provider Performance Matrix")
        print("==================================================")
        mem = SQLiteConversationMemory(db_path=settings.sqlite_db_path)
        trials = run_standard_lab_suite(memory=mem)
        print(f"  {'Provider':<14} | {'Model':<20} | {'Latency':<9} | {'Accuracy':<8} | {'Success':<7} | {'Tokens':<6}")
        print("  " + "-" * 72)
        for t in trials:
            status_str = "PASS" if t.success else "FAIL"
            print(f"  {t.provider_name:<14} | {t.model_name:<20} | {t.latency_ms:>7.1f}ms | {t.accuracy*100:>6.1f}%  | {status_str:<7} | {t.token_usage:>6}")
        print("==================================================\n")
        sys.exit(0)

    voice_requested = (args.voice or getattr(settings, "voice_enabled", False)) and not args.text
    # Clean console: default mode shows only errors; voice mode suppresses
    # provider-chain noise unless --debug is explicitly requested.
    console_log_level = logging.DEBUG if args.debug else (logging.CRITICAL if voice_requested else logging.ERROR)
    setup_logging(level=settings.log_level, log_file=settings.log_file, console_level=console_log_level)
    logger.info("Starting FRIDAY CLI session")

    if args.doctor:
        from friday.core.doctor import FridayDoctor

        report = FridayDoctor(settings=settings).run_full_diagnostics()
        print(report.to_cli_table())
        return

    if args.action_audit:
        from friday.memory.in_memory import InMemoryConversationMemory

        audit_agent = FridayAgent(
            settings=settings,
            memory=InMemoryConversationMemory(),
            tool_callback=on_tool_event,
            authorizer=CLIAuthorizer(),
        )
        print_action_audit(audit_agent)
        return

    # Perform one-time startup preflight check on Gemini pool if available
    from friday.auth.credential_pool import credential_pool
    credential_pool.preflight_check(model=settings.llm_model)

    agent = FridayAgent(
        settings=settings,
        tool_callback=on_tool_event,
        authorizer=CLIAuthorizer(),
    )

    # Voice biometrics enrollment (one-time; then exit)
    if getattr(args, "enroll_voice", False):
        import asyncio

        from friday.security.voice_biometrics import VoiceProfileManager

        manager = VoiceProfileManager()
        try:
            if asyncio.run(manager.enroll_voice(duration=5.0)):
                print("Voice profile saved. Speaker recognition is active when FRIDAY_VOICE_BIOMETRICS_ENABLED=true.")
            else:
                print("Voice enrollment failed (see log for details).")
        except Exception as e:
            print(f"Voice enrollment unavailable: {e}")
        return

    # Voice interface initialization
    # Activated either by --voice CLI flag or FRIDAY_VOICE_ENABLED=true in config (without --text override)
    is_voice_mode = voice_requested
    if is_voice_mode and args.voice and not getattr(settings, "voice_enabled", False):
        print("Voice mode enabled via CLI override (--voice; FRIDAY_VOICE_ENABLED is false).")
    if is_voice_mode:
        import asyncio
        import threading

        print(render_friday_banner("0.4.6"))
        print("  Starting Gemini Live Real-Time Voice Session...")
        print("  Model: gemini-3.1-flash-live-preview | Input: 16kHz PCM | Output: 24kHz PCM")
        if _console is not None:
            _console.print("[bold green]Listening...[/bold green] speak naturally; transcripts print live. "
                           "You can also TYPE a message")
        else:
            print("  Speak naturally; transcripts print live. You can also TYPE a message")
        print("  and press Enter to send it to the session. Press Ctrl+C to end.\n")
        try:
            from friday.voice.gemini_live_session import GeminiLiveVoiceSession
            from friday.voice.transcripts import LiveTranscriptPrinter

            # Client-side RMS barge-in disabled completely; relying 100% on Google Server-Side VAD
            voice_session = GeminiLiveVoiceSession(
                agent=agent,
                credential_pool=credential_pool,
                barge_in_rms_threshold=float("inf"),
                local_barge_in_during_playback=False,
            )
            printer = LiveTranscriptPrinter()

            loop = asyncio.new_event_loop()

            def _stdin_listener() -> None:
                """Background thread: typed lines become Live text prompts.

                Instant device commands (volume, battery, chrome, time, etc.)
                are executed locally via the agent and the verified result is
                sent back to the Live model for speaking. Conversational text
                is forwarded directly to the Live model.
                """
                while True:
                    try:
                        line = sys.stdin.readline()
                    except Exception:
                        break
                    if not line:  # EOF
                        break
                    text = line.strip()
                    if text:
                        asyncio.run_coroutine_threadsafe(
                            voice_session.process_typed_input(text), loop
                        )

            stdin_thread = threading.Thread(target=_stdin_listener, name="voice_stdin", daemon=True)
            stdin_thread.start()

            async def _greet_on_connect() -> None:
                """Make FRIDAY speak first with a brief opening greeting."""
                await voice_session._connected_event.wait()
                try:
                    await voice_session.send_text("Start the conversation by greeting me briefly.")
                    logger.info("Sent initial voice greeting prompt.")
                except Exception as e:
                    logger.warning(f"Could not send initial greeting prompt: {e}")

            # Graceful shutdown: run the live loop as a task so Ctrl+C can
            # cancel-and-drain it, letting the session's finally blocks close
            # the WebSocket before the loop exits (no 'Event loop is closed' /
            # 'Task was destroyed' warnings).
            voice_task = loop.create_task(voice_session.run_live_loop(
                on_turn_complete=printer.on_turn_complete,
                on_server_content=printer.on_server_content,
                echo_mute=True,
            ))
            greeting_task = loop.create_task(_greet_on_connect())
            try:
                loop.run_until_complete(voice_task)
                logger.info("Live Voice session ended.")
            except KeyboardInterrupt:
                print("\nVoice session stopped. Good day, Surendra.")
                voice_task.cancel()
                greeting_task.cancel()
                try:
                    loop.run_until_complete(voice_task)
                except BaseException:
                    pass
            finally:
                for t in (greeting_task, voice_task):
                    if not t.done():
                        t.cancel()
                        try:
                            loop.run_until_complete(t)
                        except BaseException:
                            pass
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass
                loop.close()
        except Exception as e:
            print(f"\n[Voice Error]: Gemini Live session failed: {e}")
            logger.error(f"Gemini Live session failed: {e}")
        return

    print(render_friday_banner("0.4.6"))

    while True:
        try:
            if _console is not None:
                user_input = _console.input(f"[bold green]{settings.user_name} > [/]").strip()
            else:
                user_input = input(f"{settings.user_name} > ").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\nShutting down FRIDAY. Good day, {settings.user_name}.")
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

        elif cmd in ("/history", "history"):
            print_history(agent)
            continue
        elif cmd in ("/status", "status"):
            print_status(agent)
            continue
        elif cmd in ("/help", "help"):
            print_help()
            continue

        # Process standard conversation turn with Rich UI & Split-View Status Panel
        try:
            start_t = datetime.now()
            global_timeline.update_status(
                cognitive_phase="PROCESSING",
                active_agent="General",
                selected_provider=getattr(agent.llm, "provider_name", "FallbackChain"),
                active_tool="None",
            )
            global_timeline.record_event(
                event_type="user_prompt",
                description=f"Received prompt: {user_input[:40]}...",
            )

            if _console is not None:
                with _console.status("[bold cyan]FRIDAY is thinking...", spinner="dots") as status:
                    _active_status["obj"] = status
                    try:
                        response = agent.process_message(user_input)
                    finally:
                        _active_status["obj"] = None

                elapsed_ms = (datetime.now() - start_t).total_seconds() * 1000.0
                phase_val = response.metadata.get("cognitive_phase", "COMPLETED") if hasattr(response, "metadata") and response.metadata else "COMPLETED"
                global_timeline.update_status(
                    cognitive_phase=phase_val,
                    last_latency_ms=elapsed_ms,
                )
                global_timeline.record_event(
                    event_type="agent_response",
                    description=f"Generated response ({len(response.content or '')} chars)",
                    duration_ms=elapsed_ms,
                )

                # Split-view output: Top half = response panel, Bottom half = Live Status Panel
                _console.print(
                    Panel(Text(response.content or "(no response)"), title=settings.agent_name,
                          border_style="cyan", padding=(0, 1)),
                )
                _console.print(render_status_panel())
                _console.print()
            else:
                response = agent.process_message(user_input)
                elapsed_ms = (datetime.now() - start_t).total_seconds() * 1000.0
                global_timeline.update_status(last_latency_ms=elapsed_ms)
                print(f"\n{settings.agent_name} > {response.content}\n")
        except Exception as e:
            print(f"\n[Error]: {e}\n")


if __name__ == "__main__":
    main()
