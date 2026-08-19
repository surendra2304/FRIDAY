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
import time
from typing import Any, Callable, Dict, List, Optional

from google import genai
from google.genai import types as genai_types

from enum import Enum

from friday.auth.credential_pool import credential_pool, GeminiCredentialPool
from friday.core.config import get_settings
from friday.core.exceptions import LLMProviderError
from friday.core.logging import get_logger, redact_tool_args
from friday.core.types import Message, Role, SafetyLevel, ToolCall
from friday.voice.audio_io import MicrophoneStream, SpeakerStream, compute_pcm_rms

logger = get_logger("voice.live_session")


class LiveSessionState(str, Enum):
    """Observable states of the real-time bidirectional Gemini Live session."""
    IDLE = "IDLE"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    USER_SPEAKING = "USER_SPEAKING"
    FRIDAY_SPEAKING = "FRIDAY_SPEAKING"
    INTERRUPTED = "INTERRUPTED"
    TOOL_CALL = "TOOL_CALL"
    RECONNECTING = "RECONNECTING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


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
        thinking_level: Optional[str] = None,
        thinking_budget: Optional[int] = None,
        credential_pool: Optional[GeminiCredentialPool] = credential_pool,
    ):
        settings = get_settings()
        self.credential_pool = credential_pool
        self._explicit_api_key = api_key
        try:
            self.api_key = api_key or (credential_pool.get_active_key() if credential_pool else None) or settings.gemini_api_key or settings.llm_api_key
        except Exception:
            self.api_key = api_key or settings.gemini_api_key or settings.llm_api_key
        if not self.api_key:
            raise ValueError("Gemini API key is required for Gemini Live voice session")
        self.model = model or getattr(settings, "voice_live_model", "gemini-3.1-flash-live-preview")
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
        self.barge_in_consecutive_frames = getattr(settings, "voice_barge_in_consecutive_frames", 3)
        self.barge_in_playback_factor = getattr(settings, "voice_barge_in_playback_factor", 2.5)
        self.barge_in_cooldown_seconds = getattr(settings, "voice_barge_in_cooldown_seconds", 0.8)
        self.headphones_mode = getattr(settings, "voice_headphones_mode", False)
        self.thinking_level = thinking_level or getattr(settings, "voice_thinking_level", "MINIMAL")
        self.thinking_budget = thinking_budget if thinking_budget is not None else getattr(settings, "voice_thinking_budget", None)

        self._active = False
        self._state = LiveSessionState.IDLE
        self._session: Optional[Any] = None
        self._resumption_handle: Optional[str] = None
        self._connected_event = asyncio.Event()

        # Barge-in debouncing & cooldown state
        self._consecutive_speech_frames: int = 0
        self._last_interruption_time: float = 0.0

    def _set_state(self, new_state: LiveSessionState) -> None:
        """Atomically transition state with audit logging."""
        if self._state != new_state:
            old = self._state
            self._state = new_state
            logger.debug(f"LiveSession state transition: {old.value} -> {new_state.value}")

    @property
    def state(self) -> LiveSessionState:
        """Return the current observable turn state."""
        return self._state

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

        # Thinking configuration (Gemini 3.1 Live uses thinking_level)
        if self.thinking_level is not None:
            try:
                level_str = str(self.thinking_level).upper()
                if hasattr(genai_types, "ThinkingLevel") and hasattr(genai_types.ThinkingLevel, level_str):
                    config_kwargs["thinking_config"] = genai_types.ThinkingConfig(thinking_level=getattr(genai_types.ThinkingLevel, level_str))
                else:
                    config_kwargs["thinking_config"] = genai_types.ThinkingConfig(thinking_level=level_str)
            except Exception as e:
                logger.debug(f"ThinkingConfig thinking_level error: {e}")
        elif self.thinking_budget is not None:
            try:
                config_kwargs["thinking_config"] = genai_types.ThinkingConfig(thinking_budget=self.thinking_budget)
            except Exception as e:
                logger.debug(f"ThinkingConfig thinking_budget error: {e}")

        # Session resumption (Developer API mode requires handle without transparent parameter)
        if self.enable_session_resumption and self._resumption_handle:
            try:
                config_kwargs["session_resumption"] = genai_types.SessionResumptionConfig(
                    handle=self._resumption_handle,
                )
            except Exception as e:
                logger.debug(f"Session resumption config error: {e}")

        return genai_types.LiveConnectConfig(**config_kwargs)

    async def _execute_tool_call(self, fc: Any) -> genai_types.FunctionResponse:
        """Execute a Gemini Live function call through the canonical FridayAgent tool path.

        Uses agent._execute_single_tool_call which owns:
        - tool lookup and registration check
        - schema / argument validation
        - SAFE / SENSITIVE / DANGEROUS classification
        - authorization gating (authorizer.authorize)
        - deduplication by call ID
        - execution with timeout
        - error normalization
        - audit logging (metadata-only, no raw args)
        """
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

        # --- SAFE structured metadata-only log (no raw argument values) ---
        registry = getattr(self.agent, "tools", getattr(self.agent, "tool_registry", None)) if self.agent else None
        tool_obj = registry.get(tool_name) if registry else None
        safety_label = tool_obj.safety_level.value if tool_obj else "unknown"
        logger.info(
            "Voice tool request [name: %s, call_id: %s, safety: %s, arg_count: %d, args_meta: %s]",
            tool_name,
            tool_id,
            safety_label,
            len(args),
            redact_tool_args(args),
        )

        # --- Delegate to canonical agent execution path ---
        if self.agent is not None and hasattr(self.agent, "_execute_single_tool_call"):
            tc = ToolCall(id=tool_id, name=tool_name, arguments=args)
            try:
                result = await asyncio.get_running_loop().run_in_executor(
                    None, self.agent._execute_single_tool_call, tc
                )
            except Exception as e:
                logger.warning("Voice tool '%s' raised unexpected exception: %s", tool_name, type(e).__name__)
                return genai_types.FunctionResponse(
                    name=tool_name,
                    id=tool_id,
                    response={"error": f"Execution error: {type(e).__name__}"},
                )

            content = result.content if not result.is_error else f"Execution error: {result.content}"
            is_sensitive = (
                result.safety_level in (SafetyLevel.SENSITIVE, SafetyLevel.DANGEROUS)
                if hasattr(result, "safety_level") else False
            )

            logger.info(
                "Voice tool completed [name: %s, call_id: %s, success: %s]",
                tool_name, tool_id, not result.is_error,
            )
        else:
            # Fallback: no agent present — only safe tool execution without authorization
            if not registry:
                return genai_types.FunctionResponse(
                    name=tool_name,
                    id=tool_id,
                    response={"error": "Agent tool registry not available"},
                )
            if not tool_obj:
                return genai_types.FunctionResponse(
                    name=tool_name,
                    id=tool_id,
                    response={"error": f"Tool '{tool_name}' not found"},
                )
            if tool_obj.safety_level != SafetyLevel.SAFE:
                logger.warning(
                    "Voice tool '%s' blocked in fallback path: safety=%s requires authorization",
                    tool_name, tool_obj.safety_level.value,
                )
                return genai_types.FunctionResponse(
                    name=tool_name,
                    id=tool_id,
                    response={"error": f"Tool '{tool_name}' blocked by authorizer: No interactive authorizer was configured."},
                )
            try:
                res = tool_obj.execute(**args)
                content = res.content if not res.is_error else f"Execution error: {res.content}"
                is_sensitive = False
            except Exception as e:
                content = f"Execution error: {type(e).__name__}: {str(e)}"
                is_sensitive = False

        # --- Persist tool result to memory (sensitive output gated from auto-embedding) ---
        if self.agent is not None and getattr(self.agent, "memory", None) is not None:
            try:
                conv_id = (
                    getattr(self.agent, "conversation_id", None)
                    or getattr(self.agent.memory, "active_conversation_id", None)
                )
                # Sensitive/dangerous tool results are stored to SQLite for audit purposes
                # but must NOT be auto-embedded into the semantic vector index.
                mem_content = "[SENSITIVE TOOL RESULT — content not embedded]" if is_sensitive else str(content)
                self.agent.memory.add_message(
                    Message(
                        role=Role.TOOL,
                        content=mem_content,
                        name=tool_name,
                        tool_call_id=tool_id,
                    ),
                    conversation_id=conv_id,
                )
            except Exception as mem_err:
                logger.debug("Error persisting live tool execution to memory: %s", type(mem_err).__name__)

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
                self._set_state(LiveSessionState.CONNECTING if reconnect_attempts == 0 else LiveSessionState.RECONNECTING)
                logger.info(f"Connecting to Gemini Live WebSocket (model: {self.model})...")

                try:
                    async with client.aio.live.connect(model=self.model, config=config) as session:
                        self._session = session
                        self._connected_event.set()
                        self._set_state(LiveSessionState.CONNECTED)
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
                        self._set_state(LiveSessionState.FAILED)
                        logger.error(f"Gemini Live session failed after {self.max_retries} reconnection attempts: {e}")
                        raise LLMProviderError(f"Gemini Live session error: {e}") from e

                    self._set_state(LiveSessionState.RECONNECTING)
                    delay = self.reconnect_delay * (2 ** (reconnect_attempts - 1))
                    logger.warning(
                        f"Gemini Live session disconnected: {e}. Reconnecting in {delay:.1f}s "
                        f"(attempt {reconnect_attempts}/{self.max_retries})..."
                    )
                    await asyncio.sleep(delay)

        finally:
            self._set_state(LiveSessionState.STOPPING)
            self._active = False
            self._session = None
            self._connected_event.clear()
            mic.stop()
            spk.stop()
            spk.close()
            self._set_state(LiveSessionState.STOPPED)
            logger.info("Gemini Live session closed.")

    async def _audio_sender_loop(
        self,
        session: Any,
        mic: MicrophoneStream,
        spk: SpeakerStream,
        stop_event: asyncio.Event,
    ) -> None:
        """Stream microphone PCM chunks continuously with robust debounced barge-in."""
        try:
            while self._active and not stop_event.is_set():
                chunk = await mic.read_chunk()
                if chunk and len(chunk) > 0:
                    now = time.time()
                    rms = compute_pcm_rms(chunk)
                    is_speaker_active = getattr(spk, "is_playing", False) or getattr(spk, "queue_size", 0) > 0

                    # Dynamic threshold calculation based on output activity and headphone mode
                    if is_speaker_active and not self.headphones_mode:
                        # Speaker is playing into room: apply higher threshold to avoid acoustic echo trigger
                        effective_threshold = self.barge_in_rms_threshold * self.barge_in_playback_factor
                    else:
                        effective_threshold = self.barge_in_rms_threshold

                    # Debounced speech energy tracking
                    if rms > effective_threshold:
                        self._consecutive_speech_frames += 1
                    else:
                        self._consecutive_speech_frames = 0

                    # Handle Barge-In Interruption while FRIDAY is speaking
                    if is_speaker_active:
                        # Check cooldown and required sustained consecutive frames (e.g. 3 frames = ~120ms)
                        is_cooldown_active = (now - self._last_interruption_time) < self.barge_in_cooldown_seconds
                        if (
                            not is_cooldown_active
                            and self._consecutive_speech_frames >= self.barge_in_consecutive_frames
                            and self._state != LiveSessionState.INTERRUPTED
                        ):
                            logger.info(
                                f"Local barge-in: sustained user speech detected (RMS: {rms:.1f}, "
                                f"frames: {self._consecutive_speech_frames}), purging speaker buffer"
                            )
                            self._set_state(LiveSessionState.INTERRUPTED)
                            self._last_interruption_time = now
                            self._consecutive_speech_frames = 0
                            spk.stop()
                    elif rms > self.barge_in_rms_threshold and self._state == LiveSessionState.CONNECTED:
                        self._set_state(LiveSessionState.USER_SPEAKING)

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

                # 1. Session Resumption Update (rate-limited logging)
                resumption_update = getattr(message, "session_resumption_update", None)
                if resumption_update:
                    new_handle = getattr(resumption_update, "new_handle", None) or getattr(resumption_update, "resumption_token", None)
                    if new_handle and new_handle != self._resumption_handle:
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
                        self._set_state(LiveSessionState.INTERRUPTED)
                        turn_interrupted = True
                        spk.stop()
                        agent_text_parts.clear()
                        agent_output_tx.clear()

                    # Stream model audio turn parts
                    model_turn = getattr(server_content, "model_turn", None)
                    if model_turn and getattr(model_turn, "parts", None):
                        if not turn_interrupted:
                            self._set_state(LiveSessionState.FRIDAY_SPEAKING)
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
                        self._set_state(LiveSessionState.CONNECTED)
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
                    self._set_state(LiveSessionState.TOOL_CALL)
                    func_responses = []
                    for fc in tool_call.function_calls:
                        resp = await self._execute_tool_call(fc)
                        func_responses.append(resp)

                    if func_responses:
                        logger.info(f"Sending {len(func_responses)} tool response(s) to Gemini Live")
                        await session.send_tool_response(function_responses=func_responses)
                    self._set_state(LiveSessionState.CONNECTED)

                # 5. Tool call cancellation
                tool_cancel = getattr(message, "tool_call_cancellation", None)
                if tool_cancel:
                    logger.info(f"Gemini Live cancelled tool calls: {getattr(tool_cancel, 'ids', [])}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"Audio receiver loop encountered exception: {e}")
