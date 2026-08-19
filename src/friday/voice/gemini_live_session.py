"""Real-time Gemini Live WebSocket session orchestrator for FRIDAY.

Utilizes official google-genai SDK (`client.aio.live.connect`) to provide:
- Full-duplex asynchronous bidirectional audio streaming
- Continuous 16 kHz 16-bit PCM input capture
- Incremental 24 kHz 16-bit PCM output playback
- Real-time barge-in / interruption handling
- Native tool execution & authorization gating
- Memory transcription commitment
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Callable, Dict, List, Optional

from google import genai
from google.genai import types as genai_types

from friday.core.config import get_settings
from friday.core.exceptions import LLMProviderError
from friday.core.logging import get_logger
from friday.core.types import Message, Role, SafetyLevel
from friday.voice.audio_io import MicrophoneStream, SpeakerStream

logger = get_logger("voice.live_session")


class GeminiLiveVoiceSession:
    """Manages an active real-time Gemini Live bidirectional WebSocket session."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        agent: Optional[Any] = None,
        voice_name: Optional[str] = None,
        sample_rate_in: int = 16000,
        sample_rate_out: int = 24000,
        max_retries: int = 3,
    ):
        settings = get_settings()
        self.api_key = api_key or settings.gemini_api_key or settings.llm_api_key
        if not self.api_key:
            raise ValueError("Gemini API key is required for Gemini Live voice session")
        self.model = model or getattr(settings, "voice_live_model", "gemini-2.5-flash-native-audio-latest")
        self.agent = agent
        self.voice_name = voice_name or getattr(settings, "voice_name", "Aoede")
        self.sample_rate_in = sample_rate_in
        self.sample_rate_out = sample_rate_out
        self.max_retries = max_retries
        self._active = False
        self._session: Optional[Any] = None

    def _build_tools_config(self) -> Optional[List[genai_types.Tool]]:
        """Extract tool schemas from agent registry and convert to GenAI tool declarations."""
        if not self.agent:
            return None
        registry = getattr(self.agent, "tools", getattr(self.agent, "tool_registry", None))
        if not registry:
            return None

        schemas = registry.get_schemas()
        if not schemas:
            return None

        func_decls = []
        for s in schemas:
            func = s.get("function", s) if isinstance(s, dict) else s
            func_decls.append(
                genai_types.FunctionDeclaration(
                    name=func.get("name", "") if isinstance(func, dict) else getattr(func, "name", ""),
                    description=func.get("description", "") if isinstance(func, dict) else getattr(func, "description", ""),
                    parameters=func.get("parameters", {}) if isinstance(func, dict) else getattr(func, "parameters", {}),
                )
            )
        return [genai_types.Tool(function_declarations=func_decls)]

    def _build_system_instruction(self) -> Optional[genai_types.Content]:
        """Construct system prompt embodying FRIDAY's futuristic, natural spoken persona."""
        settings = get_settings()
        user_name = getattr(settings, "user_name", "Surendra")
        base_prompt = (
            f"You are FRIDAY (Fully Responsive Intelligent Digital Assistant), an advanced personal AI assistant "
            f"communicating in real-time spoken voice.\n\n"
            f"CORE VOICE PERSONA:\n"
            f"- Personality: Calm, intelligent, concise, confident, natural, professional, and responsive.\n"
            f"- Speaking Style: Speak naturally and conversationally. Strongly prefer brief, direct answers.\n"
            f"  * Simple queries: 'Done.', 'It is 11:15 AM.', 'I found 12 files.'\n"
            f"  * Complex topics: Speak clearly and concisely without huge monologues.\n"
            f"  * Status cues: Provide subtle, natural cues when helpful (e.g., 'Checking that now.', 'One moment.'), but never add artificial filler to every turn.\n"
            f"  * Tools/Actions: For visible actions, state clearly (e.g., 'Opening Chrome.', 'Checking the file.'). For hidden/internal work, avoid unnecessary narration.\n"
            f"- STRICT ANTI-PATTERNS (DO NOT DO):\n"
            f"  * Do NOT repeat the user's name ({user_name}) on every turn. Use it rarely and naturally.\n"
            f"  * Do NOT use repetitive acknowledgements ('Sure!', 'Certainly!', 'I can help with that!').\n"
            f"  * Do NOT use robotic, formulaic language or forced catchphrases.\n"
            f"  * Do NOT use excessive 'Boss' or sycophantic greetings.\n"
            f"  * Do NOT give unsolicited meta-explanations of your internal reasoning.\n"
            f"- INTERRUPTION ADAPTATION:\n"
            f"  * When interrupted, immediately pivot to the user's new request without apologizing or referencing the cut-off topic unless asked.\n"
            f"- SAFETY & TOOLS:\n"
            f"  * Use tools when asked for real-time actions, calculations, file management, or memory search.\n"
            f"  * Dangerous or sensitive operations require user confirmation before proceeding."
        )

        # Inject historical memory context if agent is available
        if self.agent is not None and getattr(self.agent, "memory", None) is not None:
            try:
                recent_memories = self.agent.memory.get_context_window(max_messages=5)
                if recent_memories:
                    hist_lines = []
                    for m in recent_memories:
                        if m.content:
                            hist_lines.append(f"{m.role.value.capitalize()}: {m.content}")
                    if hist_lines:
                        base_prompt += "\n\nRecent context:\n" + "\n".join(hist_lines)
            except Exception as e:
                logger.debug(f"Could not load historical context for Live system prompt: {e}")

        return genai_types.Content(parts=[genai_types.Part.from_text(text=base_prompt)])

    async def _execute_tool_call(self, fc: Any) -> genai_types.FunctionResponse:
        """Execute a tool requested by Gemini Live through the agent's ToolRegistry."""
        tool_name = getattr(fc, "name", "")
        tool_id = getattr(fc, "id", None) or f"call_{tool_name}"
        raw_args = getattr(fc, "args", {})

        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args)
            except Exception:
                args = {"raw_input": raw_args}
        elif isinstance(raw_args, dict):
            args = raw_args
        else:
            try:
                args = dict(raw_args)
            except Exception:
                args = {}

        logger.info(f"Gemini Live requested tool: '{tool_name}' with args: {args}")

        registry = getattr(self.agent, "tools", getattr(self.agent, "tool_registry", None)) if self.agent else None
        if not registry:
            return genai_types.FunctionResponse(
                name=tool_name,
                id=tool_id,
                response={"error": "Agent tool registry not available"},
            )

        tool = registry.get(tool_name)
        if not tool:
            return genai_types.FunctionResponse(
                name=tool_name,
                id=tool_id,
                response={"error": f"Tool '{tool_name}' not found"},
            )

        # Check authorization gating
        authorizer = getattr(self.agent, "authorizer", None)
        if authorizer and tool.safety_level in (SafetyLevel.SENSITIVE, SafetyLevel.DANGEROUS):
            from friday.core.types import AuthorizationRequest, AuthorizationDecision
            try:
                auth_req = AuthorizationRequest(
                    tool_name=tool.name,
                    arguments=args,
                    safety_level=tool.safety_level,
                )
                auth_resp = authorizer.authorize(auth_req)
                is_approved = getattr(auth_resp, "decision", None) == AuthorizationDecision.APPROVED or getattr(auth_resp, "approved", False)
                reason = getattr(auth_resp, "reason", "Action not approved")
            except TypeError:
                auth_resp = authorizer.authorize(tool.name, args, tool.safety_level)
                is_approved = getattr(auth_resp, "approved", False) or getattr(auth_resp, "decision", None) == AuthorizationDecision.APPROVED
                reason = getattr(auth_resp, "reason", "Action not approved")

            if not is_approved:
                logger.warning(f"Voice tool '{tool_name}' blocked by authorizer: {reason}")
                return genai_types.FunctionResponse(
                    name=tool_name,
                    id=tool_id,
                    response={"error": f"Tool execution rejected: {reason}"},
                )

        # Execute tool safely
        try:
            res = tool.execute(**args)
            content = res.content if not res.is_error else f"Error: {res.content}"
        except Exception as e:
            content = f"Execution error: {str(e)}"

        # Record tool execution in agent conversation memory
        if self.agent is not None and getattr(self.agent, "memory", None) is not None:
            try:
                conv_id = getattr(self.agent, "conversation_id", None) or getattr(self.agent.memory, "active_conversation_id", None)
                self.agent.memory.add_message(
                    Message(
                        role=Role.TOOL,
                        content=str(content),
                        name=tool_name,
                        tool_call_id=tool_id,
                    ),
                    conversation_id=conv_id,
                )
            except Exception as mem_err:
                logger.debug(f"Error persisting live tool execution to memory: {mem_err}")

        return genai_types.FunctionResponse(
            name=tool_name,
            id=tool_id,
            response={"output": content},
        )

    async def run_live_loop(
        self,
        input_stream: Optional[MicrophoneStream] = None,
        output_stream: Optional[SpeakerStream] = None,
        on_turn_complete: Optional[Callable[[str, str], None]] = None,
        stop_event: Optional[asyncio.Event] = None,
    ) -> None:
        """Run the full-duplex asynchronous bidirectional Gemini Live loop."""
        self._active = True
        client = genai.Client(api_key=self.api_key)

        config = genai_types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=genai_types.SpeechConfig(
                voice_config=genai_types.VoiceConfig(
                    prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                        voice_name=self.voice_name
                    )
                )
            ),
            system_instruction=self._build_system_instruction(),
            tools=self._tools_config if hasattr(self, "_tools_config") else self._build_tools_config(),
        )

        mic = input_stream or MicrophoneStream(sample_rate=self.sample_rate_in)
        spk = output_stream or SpeakerStream(sample_rate=self.sample_rate_out)
        stop = stop_event or asyncio.Event()

        loop = asyncio.get_running_loop()
        mic.start(loop=loop)
        spk.start()

        logger.info(f"Connecting to Gemini Live WebSocket (model: {self.model})...")

        try:
            async with client.aio.live.connect(model=self.model, config=config) as session:
                self._session = session
                logger.info("Gemini Live WebSocket session established.")

                sender_task = asyncio.create_task(
                    self._audio_sender_loop(session, mic, spk, stop),
                    name="gemini_live_audio_sender",
                )
                receiver_task = asyncio.create_task(
                    self._audio_receiver_loop(session, spk, on_turn_complete, stop),
                    name="gemini_live_audio_receiver",
                )

                # Wait until interrupted or stopped
                done, pending = await asyncio.wait(
                    [sender_task, receiver_task, asyncio.create_task(stop.wait())],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        except Exception as e:
            logger.error(f"Gemini Live session error: {e}")
            raise LLMProviderError(f"Gemini Live session error: {e}") from e
        finally:
            self._active = False
            self._session = None
            mic.stop()
            spk.stop()
            spk.close()
            logger.info("Gemini Live session closed.")

    async def _audio_sender_loop(
        self,
        session: Any,
        mic: MicrophoneStream,
        spk: SpeakerStream,
        stop_event: asyncio.Event,
    ) -> None:
        """Stream microphone PCM chunks continuously with local zero-latency barge-in."""
        from friday.voice.audio_io import compute_pcm_rms

        try:
            while self._active and not stop_event.is_set():
                chunk = await mic.read_chunk()
                if chunk and len(chunk) > 0:
                    # Zero-latency local barge-in: If user speaks while speaker buffer is active, purge playback immediately
                    if getattr(spk, "is_playing", False) or getattr(spk, "queue_size", 0) > 0:
                        rms = compute_pcm_rms(chunk)
                        if rms > 350.0:  # User voice energy threshold
                            logger.info(f"Local barge-in: user speech energy detected (RMS: {rms:.1f}), purging speaker buffer")
                            spk.stop()

                    await session.send_realtime_input(
                        media_chunks=[
                            genai_types.Blob(
                                data=chunk,
                                mime_type=f"audio/pcm;rate={self.sample_rate_in}",
                            )
                        ]
                    )
                else:
                    await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"Audio sender loop encountered exception: {e}")

    async def _audio_receiver_loop(
        self,
        session: Any,
        spk: SpeakerStream,
        on_turn_complete: Optional[Callable[[str, str], None]],
        stop_event: asyncio.Event,
    ) -> None:
        """Consume server responses, stream audio chunks, and handle instant barge-in."""
        user_transcript_accum = []
        agent_text_parts = []
        agent_output_tx = []
        turn_interrupted = False

        try:
            async for message in session.receive():
                if stop_event.is_set() or not self._active:
                    break

                # 1. Server content (Audio, Transcriptions, Interruption)
                server_content = getattr(message, "server_content", None)
                if server_content:
                    # Instant barge-in / Interruption from Live API
                    if getattr(server_content, "interrupted", False) is True:
                        logger.info("Server barge-in signal: interrupting local speaker playback")
                        turn_interrupted = True
                        spk.stop()
                        agent_text_parts.clear()
                        agent_output_tx.clear()

                    # Stream model audio turn parts
                    model_turn = getattr(server_content, "model_turn", None)
                    if model_turn and getattr(model_turn, "parts", None):
                        for part in model_turn.parts:
                            # Stream raw 24kHz PCM audio chunk immediately
                            inline_data = getattr(part, "inline_data", None)
                            if inline_data and getattr(inline_data, "data", None):
                                spk.play_chunk(inline_data.data)

                            # Accumulate text parts
                            if getattr(part, "text", None):
                                agent_text_parts.append(part.text)

                    # Accumulate transcriptions if provided
                    in_tx = getattr(server_content, "input_transcription", None)
                    if in_tx and getattr(in_tx, "text", None):
                        user_transcript_accum.append(in_tx.text)

                    out_tx = getattr(server_content, "output_transcription", None)
                    if out_tx and getattr(out_tx, "text", None):
                        agent_output_tx.append(out_tx.text)

                    # Turn completion
                    if getattr(server_content, "turn_complete", False):
                        user_text = "".join(user_transcript_accum).strip()
                        raw_agent_text = ("".join(agent_output_tx).strip() or "".join(agent_text_parts).strip())
                        agent_text = f"{raw_agent_text} [interrupted]" if (turn_interrupted and raw_agent_text) else raw_agent_text

                        # Check backup spoken stop command
                        if user_text.lower() in ("stop", "stop.", "cancel", "cancel.", "hold on", "quiet"):
                            logger.info(f"Spoken stop command recognized: '{user_text}'")
                            spk.stop()
                            agent_text = "[Stopped by user]"

                        if on_turn_complete:
                            on_turn_complete(user_text, agent_text)

                        # Commit completed turn into SQLite conversation memory without corrupted state
                        if self.agent is not None and getattr(self.agent, "memory", None) is not None:
                            conv_id = getattr(self.agent, "conversation_id", None) or getattr(self.agent.memory, "active_conversation_id", None)
                            if user_text:
                                self.agent.memory.add_message(Message(role=Role.USER, content=user_text), conversation_id=conv_id)
                            if agent_text:
                                self.agent.memory.add_message(Message(role=Role.ASSISTANT, content=agent_text), conversation_id=conv_id)

                        user_transcript_accum.clear()
                        agent_text_parts.clear()
                        agent_output_tx.clear()
                        turn_interrupted = False

                # 2. Server tool execution requests
                tool_call = getattr(message, "tool_call", None)
                if tool_call and getattr(tool_call, "function_calls", None):
                    func_responses = []
                    for fc in tool_call.function_calls:
                        resp = await self._execute_tool_call(fc)
                        func_responses.append(resp)

                    if func_responses:
                        logger.info(f"Sending {len(func_responses)} tool response(s) to Gemini Live")
                        await session.send_tool_response(function_responses=func_responses)

                # 3. Tool call cancellation
                tool_cancel = getattr(message, "tool_call_cancellation", None)
                if tool_cancel:
                    logger.debug(f"Gemini Live cancelled tool calls: {getattr(tool_cancel, 'ids', [])}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"Audio receiver loop encountered exception: {e}")
