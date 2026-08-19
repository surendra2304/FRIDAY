"""Real-time Gemini Live WebSocket session orchestrator for FRIDAY.

Utilizes official google-genai SDK (`client.aio.live.connect`) to provide:
- Full-duplex asynchronous bidirectional audio streaming
- Continuous 16 kHz 16-bit mono PCM input capture
- Incremental 24 kHz 16-bit mono PCM output playback
- Real-time dual-layer barge-in / interruption handling
- Native tool execution & authorization gating
- Session resumption & GoAway reconnection lifecycle management
- Automatic memory transcription commitment
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Dict, List, Optional

from google import genai
from google.genai import types as genai_types

from friday.core.config import get_settings
from friday.core.exceptions import LLMProviderError
from friday.core.logging import get_logger
from friday.core.types import Message, Role, SafetyLevel
from friday.voice.audio_io import MicrophoneStream, SpeakerStream, compute_pcm_rms

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
        reconnect_delay: float = 1.0,
        enable_session_resumption: bool = True,
        enable_context_compression: bool = True,
        vad_start_sensitivity: Optional[str] = None,
        vad_end_sensitivity: Optional[str] = None,
        vad_prefix_padding_ms: Optional[int] = None,
        vad_silence_duration_ms: Optional[int] = None,
        barge_in_rms_threshold: Optional[float] = None,
        thinking_budget: Optional[int] = None,
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
        self.reconnect_delay = reconnect_delay
        self.enable_session_resumption = enable_session_resumption
        self.enable_context_compression = enable_context_compression

        # VAD & Barge-in settings
        self.vad_start_sensitivity = vad_start_sensitivity or getattr(settings, "voice_vad_start_sensitivity", "HIGH")
        self.vad_end_sensitivity = vad_end_sensitivity or getattr(settings, "voice_vad_end_sensitivity", "HIGH")
        self.vad_prefix_padding_ms = vad_prefix_padding_ms if vad_prefix_padding_ms is not None else getattr(settings, "voice_vad_prefix_padding_ms", 200)
        self.vad_silence_duration_ms = vad_silence_duration_ms if vad_silence_duration_ms is not None else getattr(settings, "voice_vad_silence_duration_ms", 400)
        self.barge_in_rms_threshold = barge_in_rms_threshold if barge_in_rms_threshold is not None else getattr(settings, "voice_barge_in_rms_threshold", 350.0)
        self.thinking_budget = thinking_budget if thinking_budget is not None else getattr(settings, "voice_thinking_budget", 0)

        self._active = False
        self._session: Optional[Any] = None
        self._resumption_handle: Optional[str] = None
        self._connected_event = asyncio.Event()

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def is_connected(self) -> bool:
        return self._session is not None and self._active

    @property
    def resumption_handle(self) -> Optional[str]:
        return self._resumption_handle

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
            f"You are FRIDAY (Fully Responsive Intelligent Digital Assistant), a premium, personal AI assistant "
            f"communicating in real-time spoken voice.\n\n"
            f"CORE VOICE PERSONA & PRINCIPLES:\n"
            f"- Personality: Calm, intelligent, concise, confident, natural, and efficient.\n"
            f"- Speaking Style: Spoken voice responses should be concise, crisp, and direct.\n"
            f"  * Simple queries: Respond with minimal words (e.g. 'It is 2:14 PM.', 'Done.', 'I found 3 files.').\n"
            f"  * Explanations: Deliver key information clearly without rambling monologues, allowing the user to take control quickly.\n"
            f"  * Speech Optimization: Never speak raw JSON, code symbols, markdown formatting (*, #, `), internal tool IDs, or debugging metadata.\n"
            f"- ADDRESSING THE USER:\n"
            f"  * The user is {user_name}. Use their name naturally when appropriate, but do NOT prepend or repeat it on every response.\n"
            f"  * Never use sycophantic titles like 'Boss' or fake catchphrases.\n"
            f"  * Never use customer-service filler ('Certainly!', 'I would be happy to assist you with that.').\n"
            f"- INTERRUPTION RECOVERY:\n"
            f"  * When interrupted, immediately pivot to the user's new request without apologizing or referencing the cut-off topic unless asked.\n"
            f"- SAFETY & TOOLS:\n"
            f"  * Use tools when asked for real-time actions, calculations, file management, or memory search.\n"
            f"  * Dangerous or sensitive operations require explicit user authorization."
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

    def _build_live_config(self) -> genai_types.LiveConnectConfig:
        """Construct standard LiveConnectConfig with audio, transcription, and resilience settings."""
        config_kwargs: Dict[str, Any] = {
            "response_modalities": ["AUDIO"],
            "speech_config": genai_types.SpeechConfig(
                voice_config=genai_types.VoiceConfig(
                    prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                        voice_name=self.voice_name
                    )
                )
            ),
            "system_instruction": self._build_system_instruction(),
            "tools": self._build_tools_config(),
        }

        # Transcriptions
        try:
            config_kwargs["input_audio_transcription"] = genai_types.AudioTranscriptionConfig()
            config_kwargs["output_audio_transcription"] = genai_types.AudioTranscriptionConfig()
        except Exception as e:
            logger.debug(f"Transcription config not supported: {e}")

        # VAD & Activity Detection
        try:
            start_sens = (
                genai_types.StartSensitivity.START_SENSITIVITY_HIGH
                if str(self.vad_start_sensitivity).upper() == "HIGH"
                else genai_types.StartSensitivity.START_SENSITIVITY_LOW
            )
            end_sens = (
                genai_types.EndSensitivity.END_SENSITIVITY_HIGH
                if str(self.vad_end_sensitivity).upper() == "HIGH"
                else genai_types.EndSensitivity.END_SENSITIVITY_LOW
            )
            config_kwargs["realtime_input_config"] = genai_types.RealtimeInputConfig(
                automatic_activity_detection=genai_types.AutomaticActivityDetection(
                    start_of_speech_sensitivity=start_sens,
                    end_of_speech_sensitivity=end_sens,
                    prefix_padding_ms=self.vad_prefix_padding_ms,
                    silence_duration_ms=self.vad_silence_duration_ms,
                )
            )
        except Exception as e:
            logger.debug(f"Realtime VAD config error: {e}")

        # Thinking configuration (0 = minimal thinking, lowest latency for live voice)
        if self.thinking_budget is not None:
            try:
                config_kwargs["thinking_config"] = genai_types.ThinkingConfig(thinking_budget=self.thinking_budget)
            except Exception as e:
                logger.debug(f"ThinkingConfig error: {e}")

        # Session resumption
        if self.enable_session_resumption and self._resumption_handle:
            try:
                config_kwargs["session_resumption"] = genai_types.SessionResumptionConfig(
                    handle=self._resumption_handle,
                    transparent=True,
                )
            except Exception as e:
                logger.debug(f"Session resumption config error: {e}")

        return genai_types.LiveConnectConfig(**config_kwargs)

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
        """Run the full-duplex asynchronous bidirectional Gemini Live loop with reconnection management."""
        self._active = True
        client = genai.Client(api_key=self.api_key)

        mic = input_stream or MicrophoneStream(sample_rate=self.sample_rate_in)
        spk = output_stream or SpeakerStream(sample_rate=self.sample_rate_out)
        stop = stop_event or asyncio.Event()

        loop = asyncio.get_running_loop()
        mic.start(loop=loop)
        spk.start()

        reconnect_attempts = 0

        try:
            while self._active and not stop.is_set():
                config = self._build_live_config()
                logger.info(f"Connecting to Gemini Live WebSocket (model: {self.model})...")

                try:
                    async with client.aio.live.connect(model=self.model, config=config) as session:
                        self._session = session
                        self._connected_event.set()
                        reconnect_attempts = 0  # Reset retry counter on successful connection
                        logger.info("Gemini Live WebSocket session established.")

                        sender_task = asyncio.create_task(
                            self._audio_sender_loop(session, mic, spk, stop),
                            name="gemini_live_audio_sender",
                        )
                        receiver_task = asyncio.create_task(
                            self._audio_receiver_loop(session, spk, on_turn_complete, stop),
                            name="gemini_live_audio_receiver",
                        )

                        # Wait until interrupted, stopped, or disconnected
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
                    self._session = None
                    self._connected_event.clear()
                    if stop.is_set() or not self._active:
                        break

                    reconnect_attempts += 1
                    if reconnect_attempts > self.max_retries:
                        logger.error(f"Gemini Live session failed after {self.max_retries} reconnection attempts: {e}")
                        raise LLMProviderError(f"Gemini Live session error: {e}") from e

                    delay = self.reconnect_delay * (2 ** (reconnect_attempts - 1))
                    logger.warning(
                        f"Gemini Live session disconnected: {e}. Reconnecting in {delay:.1f}s "
                        f"(attempt {reconnect_attempts}/{self.max_retries})..."
                    )
                    await asyncio.sleep(delay)

        finally:
            self._active = False
            self._session = None
            self._connected_event.clear()
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
        try:
            while self._active and not stop_event.is_set():
                chunk = await mic.read_chunk()
                if chunk and len(chunk) > 0:
                    # Zero-latency local barge-in: If user speaks while speaker buffer is active, purge playback immediately
                    if getattr(spk, "is_playing", False) or getattr(spk, "queue_size", 0) > 0:
                        rms = compute_pcm_rms(chunk)
                        if rms > self.barge_in_rms_threshold:  # User voice energy threshold
                            logger.info(f"Local barge-in: user speech energy detected (RMS: {rms:.1f}), purging speaker buffer")
                            spk.stop()

                    blob = genai_types.Blob(
                        data=chunk,
                        mime_type=f"audio/pcm;rate={self.sample_rate_in}",
                    )
                    try:
                        await session.send_realtime_input(audio=blob)
                    except TypeError:
                        try:
                            await session.send_realtime_input(media=blob)
                        except TypeError:
                            await session.send_realtime_input(media_chunks=[blob])
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

                # 1. Session Resumption Update
                resumption_update = getattr(message, "session_resumption_update", None)
                if resumption_update:
                    new_handle = getattr(resumption_update, "new_handle", None) or getattr(resumption_update, "resumption_token", None)
                    if new_handle:
                        self._resumption_handle = new_handle
                        logger.debug("Gemini Live session resumption handle updated.")

                # 2. Server GoAway Signal
                go_away = getattr(message, "go_away", None)
                if go_away:
                    logger.warning("Gemini Live server sent GoAway signal; preparing for reconnection.")
                    break

                # 3. Server content (Audio, Transcriptions, Interruption)
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

                # 4. Server tool execution requests
                tool_call = getattr(message, "tool_call", None)
                if tool_call and getattr(tool_call, "function_calls", None):
                    func_responses = []
                    for fc in tool_call.function_calls:
                        resp = await self._execute_tool_call(fc)
                        func_responses.append(resp)

                    if func_responses:
                        logger.info(f"Sending {len(func_responses)} tool response(s) to Gemini Live")
                        await session.send_tool_response(function_responses=func_responses)

                # 5. Tool call cancellation
                tool_cancel = getattr(message, "tool_call_cancellation", None)
                if tool_cancel:
                    logger.info(f"Gemini Live cancelled tool calls: {getattr(tool_cancel, 'ids', [])}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"Audio receiver loop encountered exception: {e}")
