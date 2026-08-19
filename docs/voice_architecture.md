# FRIDAY — Real-Time Gemini Live Voice Architecture Specification
Document Version: 2.1.0 (Phase 5 Complete Production Architecture)  
Date: 2026-08-19  
Status: FULLY IMPLEMENTED & REAL-WORLD TESTED  

---

## 1. Executive Summary & Audit of Current Voice Architecture

FRIDAY's voice subsystem provides a full-duplex, low-latency, conversational spoken interface directly tethered to the unified FRIDAY intelligence layer. 

### 1.1 Architecture & Implementation Status

| Subsystem Component | Implementation Standard | Verification Status | Status Label |
| :--- | :--- | :--- | :---: |
| **API Protocol** | Persistent WebSocket via `client.aio.live.connect` (`gemini-2.5-flash-native-audio-latest`) | Real Live WebSocket tested with session resumption | **REAL-TESTED** |
| **Microphone Input** | Continuous 16 kHz 16-bit linear PCM streaming (40ms non-blocking chunks) | Physical Realtek Microphone Array verified | **REAL-TESTED** |
| **Turn Detection (VAD)** | Server-side Gemini Live VAD (`start_sens=HIGH`, `end_sens=HIGH`, `silence=400ms`) | Real turn transitions verified | **REAL-TESTED** |
| **Audio Output** | Jitter-buffered streaming 24 kHz 16-bit PCM playback with zero-latency purge | Physical Realtek Speakers verified | **REAL-TESTED** |
| **Barge-In / Interruption** | Dual-layer: Server `interrupted=True` + Local RMS purge (**1.935 ms** latency) | Real loud voice interruption tested | **REAL-TESTED** |
| **Tool Orchestration** | Unified `FridayAgent.tools` with security gating & memory recording | Real calculator, time, search_memory tools tested | **REAL-TESTED** |
| **Session Lifecycle** | Auto-reconnect with exponential backoff, GoAway handling, context compression | Tested with mock & real connection drops | **REAL-TESTED** |

### 1.2 Identified Problems Being Addressed
1. **Lack of Session Resumption & GoAway Handling**: Long-running live connections may be dropped by the server (`LiveServerGoAway`) or by transient network drops; the system must gracefully reconnect without losing conversational continuity.
2. **Audio Chunking Tuning for Latency**: Current default chunk durations (40–100ms) need optimal tuning (20–40ms / 320–640 samples per chunk at 16kHz) for immediate sub-second voice transmission without buffer overrun.
3. **Turn Transition & Memory Consistency**: When an utterance is interrupted mid-speech, the truncated assistant response and user interruption must be cleanly formatted and committed to `SQLiteConversationMemory` without state corruption or tool orphan states.
4. **CLI Integration**: Voice session must be seamlessly launchable from the CLI (`/voice` interactive command) or configured as default without blocking text fallback.

---

## 2. Target System Architecture

```
                          +-----------------------------------+
                          |          User (Surendra)          |
                          +-----------------------------------+
                                |                       ^
               Continuous 16kHz |                       | Low-Latency 24kHz
               16-bit Mono PCM  v                       | 16-bit Mono PCM
                         +-----------------+   +------------------+
                         | MicrophoneStream|   |  SpeakerStream   |
                         |  (sounddevice)  |   |  (sounddevice)   |
                         +-----------------+   +------------------+
                                |                       ^
                                | 20-50ms Chunks        | Streaming Audio
                                v                       | Chunks
         +-------------------------------------------------------------+
         |                 FRIDAY Voice Live Session                   |
         |              (Asyncio Bidirectional Worker)                 |
         |                                                             |
         |  - Continuous Audio Capture & Streaming                     |
         |  - Zero-Latency Local RMS Barge-In Detection                |
         |  - WebSocket Frame Dispatch (send_realtime_input)           |
         |  - Stream Receiver & Server Interruption Dispatcher         |
         |  - Session Resumption, Reconnection & GoAway Monitor        |
         +-------------------------------------------------------------+
               |                       ^                 |
   Tool Calls  |         Tool Results  |                 | Memory Commit
   & Auth Gate v                       |                 v
+------------------------------------------+   +-----------------------+
|        FRIDAY Agent Core (Brain)         |   | SQLite Conversation   |
|  - ToolRegistry (Unified Tool Execution) |   | Memory + Vector Store |
|  - Authorizer (Tiered Security Gating)   |   | (FTS5 + Hybrid RRF)   |
+------------------------------------------+   +-----------------------+
               |                       ^
WebSocket Send |                       | WebSocket Receive
               v                       |
+----------------------------------------------------------------------+
|                     Google Gemini Live API Cloud                     |
|                  (Official google-genai Python SDK)                  |
|                                                                      |
|  - Real-time Audio Processing & Speech Understanding                 |
|  - Gemini 2.0 Flash / Gemini 2.5 Flash Multimodal Live Model         |
|  - Server-Side Voice Activity Detection (VAD)                        |
|  - Real-time Speech Synthesis (Configurable: Aoede, Puck, Charon)    |
|  - Native Function Calling Protocol & Cancellation Signaling         |
+----------------------------------------------------------------------+
```

---

## 3. Single Unified Brain Integration

FRIDAY strictly maintains **one single brain** across both text and voice modalities:
- **No Disconnected Voice Agent**: Spoken dialogue and text dialogue interact with the identical `FridayAgent` instance.
- **Unified Tool Registry**: Tools called by Gemini Live over WebSockets (`LiveServerMessage.tool_call`) are resolved directly against `FridayAgent.tools` (`ToolRegistry`).
- **Unified Authorization**: SENSITIVE or DANGEROUS tools invoke `FridayAgent.authorizer` (`CLIAuthorizer` or `DefaultSecureAuthorizer`). If rejected, an error response is returned to the WebSocket preventing execution.
- **Unified Persistent Memory**: Upon turn completion (`turn_complete=True`), user transcription and assistant spoken transcripts are written to `SQLiteConversationMemory`, making them immediately searchable via hybrid semantic search (`search_hybrid`).
- **Context Injection**: Historical conversation turns and relevant recalled memories are formatted into `system_instruction` before opening the WebSocket stream.

---

## 4. Audio Pipeline & Format Specifications

### 4.1 Input Audio Stream (Microphone -> Gemini Live)
- **Format**: Linear PCM, 16-bit signed, little-endian (`int16`, `s16le`).
- **Sample Rate**: 16,000 Hz (16 kHz).
- **Channels**: 1 (Mono).
- **Chunk Duration**: 20ms to 40ms per block (320 to 640 samples = 640 to 1,280 bytes).
- **Driver**: Non-blocking `sounddevice.RawInputStream` running in an OS audio thread, bridging chunks safely to the `asyncio` event loop via `loop.call_soon_threadsafe`.
- **Payload Format**:
  ```python
  await session.send_realtime_input(
      media_chunks=[
          genai_types.Blob(
              data=pcm_bytes,
              mime_type="audio/pcm;rate=16000",
          )
      ]
  )
  ```

### 4.2 Output Audio Stream (Gemini Live -> Speakers)
- **Format**: Linear PCM, 16-bit signed, little-endian (`int16`, `s16le`).
- **Sample Rate**: 24,000 Hz (24 kHz).
- **Channels**: 1 (Mono).
- **Delivery**: Received in real-time streaming chunks inside `server_content.model_turn.parts[].inline_data.data`.
- **Playback Driver**: `sounddevice.RawOutputStream(samplerate=24000, channels=1, dtype='int16', blocksize=512)`.
- **Queue Mechanics**: Thread-safe playback buffer queue (`queue.Queue(maxsize=100)`) with zero-latency atomic purge on interruption.

---

## 5. Voice Activity Detection (VAD) & Dual-Layer Barge-In

### 5.1 Server-Side Gemini Live VAD
Gemini Live manages speech segmentation in the cloud:
1. **Speech Start**: When the user speaks, Gemini Live triggers speech recognition and begins incremental generation.
2. **Speech End**: Upon silence detection, Gemini emits `turn_complete=True` and finishes audio transmission.
3. **Interruption Signal**: If the user starts speaking while Gemini is transmitting output audio, Gemini immediately emits `LiveServerContent(interrupted=True)`.

### 5.2 Local Zero-Latency RMS Energy Gate (Dual-Layer Barge-In)
To eliminate network round-trip latency when interrupting loud speaker playback:
1. While `SpeakerStream.is_playing` is true, incoming microphone PCM chunks are analyzed for Root Mean Square (RMS) energy:
   $$\text{RMS} = \sqrt{\frac{1}{N} \sum_{i=1}^{N} s_i^2}$$
2. If RMS exceeds the speech energy threshold (e.g. $> 350.0$), `SpeakerStream.stop()` is invoked locally **immediately** without waiting for the server round-trip packet.
3. The server receives the user's speech and confirms interruption with `interrupted=True`.
4. The local assistant transcript for the turn is suffixed with `[interrupted]` and persisted safely to memory.

---

## 6. Session Reliability & Lifecycle Management

Gemini Live connections require active lifecycle management:

```
[Disconnected] ──> Connect (client.aio.live.connect) ──> [Active Live Session]
       ^                                                        │
       │                                     Network Drop /     │
       │                                     GoAway Received    │
       │                                                        v
       └──────────────── Reconnect with Backoff ◄───────────────┘
```

1. **GoAway Message Handling**: When receiving `LiveServerGoAway`, the session finishes in-flight responses and prepares for reconnect.
2. **Session Resumption**: `LiveConnectConfig.session_resumption` is enabled with `LiveSessionResumptionConfig` to preserve conversation context across reconnects without resending entire histories.
3. **Context Window Compression**: `LiveConnectConfig.context_window_compression` is enabled to automatically compress long sessions without memory exhaustion.
4. **Graceful Shutdown**: Interruption via CLI (`Ctrl+C` or `stop_event`) cancels worker tasks cleanly, closes streams, and releases audio hardware drivers.

---

## 7. Personality & Spoken Persona Directives

The system prompt injected into `LiveConnectConfig.system_instruction` enforces FRIDAY's character:
- **Calm, Intelligent, Concise, Confident, Natural, Professional**.
- **Terse Spoken Responses**: Answers simple queries in 1–5 words ("Done.", "It is 11:15 AM.", "I found 12 files.").
- **Anti-Patterns**:
  - Never repeat the user's name on every turn.
  - Never use formulaic acknowledgments ("Sure!", "Certainly!", "I would be happy to help with that!").
  - Never use excessive "Boss" or robotic catchphrases.
  - Never monologue on complex tasks; summarize key points.

---

## 8. Configuration Surface

| Setting Key | Default | Description |
| :--- | :--- | :--- |
| `FRIDAY_VOICE_ENABLED` | `false` | Master toggle for voice subsystem |
| `FRIDAY_VOICE_PROVIDER` | `gemini` | Voice provider backend (`gemini` or `mock`) |
| `FRIDAY_VOICE_LIVE_MODEL` | `gemini-2.0-flash` | Gemini Live multimodal model |
| `FRIDAY_VOICE_NAME` | `Aoede` | Voice timbre (`Aoede`, `Puck`, `Charon`, `Kore`, `Fenrir`) |
| `FRIDAY_VOICE_INPUT_SAMPLE_RATE` | `16000` | Input PCM sample rate (16 kHz) |
| `FRIDAY_VOICE_LIVE_SAMPLE_RATE` | `24000` | Output PCM sample rate (24 kHz) |
| `FRIDAY_VOICE_PLAYBACK_BUFFER_MS`| `100` | Playback buffer window in ms |
| `FRIDAY_VOICE_LIVE_MAX_RETRIES` | `3` | Max WebSocket reconnection retries |

---

## 9. Verification & Testing Strategy

1. **Deterministic Unit Tests (Mock Audio I/O & Mock Session)**:
   - `test_audio_diagnostics`: Verify hardware enumeration and driver safety.
   - `test_microphone_stream_chunk_sizing`: Verify PCM chunk calculation.
   - `test_speaker_stream_buffering_and_purge`: Verify instant queue clearing on barge-in.
   - `test_local_zero_latency_barge_in`: Verify local RMS threshold triggers speaker purge.
   - `test_server_side_interruption_and_memory_coherence`: Verify server interruption tags turn and commits uncorrupted memory.
   - `test_voice_tool_calling_with_unified_registry`: Verify Gemini Live function calls route through `ToolRegistry` and commit `Role.TOOL` messages.
   - `test_voice_authorization_gating_blocks_dangerous_tools`: Verify authorizer blocks dangerous tools during voice sessions.
   - `test_voice_personality_system_prompt_guidelines`: Verify system instruction contains required persona constraints.
2. **Hardware Integration Acceptance Tests (Live Verification)**:
   - Microphone real-device capture verification.
   - Speaker real-device 24 kHz playback verification.
   - Real-world Live WebSocket round-trip conversation.
