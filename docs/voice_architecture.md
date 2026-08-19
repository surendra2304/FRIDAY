# FRIDAY — Phase 5 Real-Time Gemini Live Voice Architecture

## 1. Executive Summary & Architectural Evolution

FRIDAY is transitioning from a turn-based request-response audio pipeline (fixed 4-second chunk recording, batch transcription, and post-response speech synthesis) to a **full-duplex, low-latency, real-time Gemini Live WebSocket session**.

### Problem Statement (Legacy vs. Target)
| Dimension | Legacy Phase 4 Implementation | Target Phase 5 Gemini Live Architecture |
| :--- | :--- | :--- |
| **Communication Protocol** | Discrete HTTP `generate_content` calls | Bidirectional WebSocket stream via `client.aio.live.connect` |
| **Microphone Input** | Fixed 4.0-second blocking WAV recording | Continuous 16 kHz 16-bit PCM audio stream (50–100ms chunks) |
| **Turn Detection** | Hardcoded recording timeout | Automatic Gemini Live Voice Activity Detection (VAD) |
| **Audio Output** | Batch MP3 download and synchronous play | Low-latency 24 kHz 16-bit PCM streaming to output buffer |
| **Interruption (Barge-In)** | Not supported; user must wait for full speech | Immediate playback abortion upon `interrupted=True` signal |
| **Tool Execution** | Re-invoked via separate text turns | Native WebSocket tool calls via `LiveServerMessage.tool_call` |
| **Laptop Resource Load** | Zero local inference (cloud API) | Zero local inference (cloud WebSocket streaming) |

```
                       +-----------------------------------+
                       |          User (Surendra)          |
                       +-----------------------------------+
                             |                       ^
                 Continuous  |                       |  Low-Latency
                 16kHz PCM   v                       |  24kHz PCM
                       +-----------------+   +------------------+
                       | MicrophoneInput |   | AudioOutputQueue |
                       +-----------------+   +------------------+
                             |                       ^
                             |                       | Streamed Audio
                             v                       | Chunks
        +-------------------------------------------------------------+
        |                 FRIDAY Voice Live Session                   |
        |              (Asyncio Bidirectional Worker)                 |
        |                                                             |
        |  - Sends Realtime Audio Chunks (send_realtime_input)        |
        |  - Receives Server Content & Audio Stream (receive)         |
        |  - Handles Barge-in / Interruption (clears playback queue)  |
        |  - Integrates Tool Execution & Authorization Gating         |
        |  - Logs Completed Turns to SQLite Conversation Memory       |
        +-------------------------------------------------------------+
                             |                       ^
              WebSocket Send |                       | WebSocket Receive
                             v                       |
        +-------------------------------------------------------------+
        |                Google Gemini Live API Cloud                 |
        |                   (google-genai SDK)                        |
        |                                                             |
        |  - Real-time Audio Processing & Speech Understanding        |
        |  - Gemini 2.0 / 2.5 Live Multimodal Model                   |
        |  - Server-side VAD & Interruption Management                |
        |  - Native Tool Calling & Streaming Speech Synthesis         |
        +-------------------------------------------------------------+
```

---

## 2. Gemini Live API Integration (`google-genai`)

The implementation strictly uses the official **`google-genai`** Python SDK (`from google import genai` and `google.genai.types`).

### Connection Setup
```python
from google import genai
from google.genai import types as genai_types

client = genai.Client(api_key=settings.gemini_api_key)

# Configure tools from FRIDAY's existing ToolRegistry
tool_declarations = [
    genai_types.FunctionDeclaration(
        name=t["name"],
        description=t["description"],
        parameters=t["parameters"],
    )
    for t in tool_registry.get_schemas()
]

config = genai_types.LiveConnectConfig(
    response_modalities=[genai_types.LiveModality.AUDIO],
    speech_config=genai_types.SpeechConfig(
        voice_config=genai_types.VoiceConfig(
            prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                voice_name="Puck"  # Configurable: Puck, Charon, Aoede, Fenrir, Kore
            )
        )
    ),
    system_instruction=genai_types.Content(
        parts=[genai_types.Part.from_text(text=system_prompt)]
    ),
    tools=[genai_types.Tool(function_declarations=tool_declarations)],
)

async with client.aio.live.connect(model=settings.voice_live_model, config=config) as session:
    # Full-duplex send / receive tasks
    ...
```

### Configurable Model Architecture
The Live model is decoupled and configurable in `Settings`:
* `FRIDAY_VOICE_LIVE_MODEL` defaults to `gemini-2.0-flash` (or `gemini-2.0-flash-exp` / `gemini-2.5-flash`).
* No hardcoded legacy or deprecated preview strings.

---

## 3. Audio Stream Specifications & Mechanics

### Input Audio Stream (Microphone -> Gemini Live)
* **Format**: Linear PCM, 16-bit signed, little-endian (`int16`).
* **Sample Rate**: 16,000 Hz (16 kHz), single channel (mono).
* **Chunking**: Non-blocking audio stream generating chunks every 50ms–100ms (800–1600 samples = 1,600–3,200 bytes).
* **Payload Transmission**:
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

### Output Audio Stream (Gemini Live -> Local Speaker)
* **Format**: Linear PCM, 16-bit signed (`int16`).
* **Sample Rate**: 24,000 Hz (24 kHz), single channel (mono).
* **Delivery**: Received in streaming chunks via `server_content.model_turn.parts[].inline_data.data`.
* **Playback Mechanics**: Chunks are enqueued into an asynchronous, non-blocking playback stream (e.g. `sounddevice.RawOutputStream(samplerate=24000, channels=1, dtype='int16')`).

---

## 4. Voice Activity Detection (VAD) & Barge-In Architecture

### Automatic Turn-Taking & VAD
Gemini Live features built-in server-side Voice Activity Detection:
1. **Speech Start**: When the user begins speaking, Gemini detects vocal energy and begins streaming input processing.
2. **Speech End**: When the user finishes speaking, Gemini produces `turn_complete=True` and generates its vocal response.

### Instant Barge-In (Interruption Handling)
When the user speaks while FRIDAY is vocalizing:
1. Gemini Live detects user speech over the microphone input.
2. Gemini immediately sends a `LiveServerContent` message with `interrupted=True`.
3. **Local Action**:
   - The FRIDAY voice worker instantly halts the local audio playback stream.
   - Clears all buffered 24 kHz PCM audio chunks from the playback queue.
   - Sets speech status to listening, ensuring zero latency before hearing the user's new instruction.
4. If a tool call was in-flight when interrupted, Gemini emits `tool_call_cancellation` to discard aborted executions.

---

## 5. Single Unified Brain Integration

The voice subsystem is **not** a disconnected second agent. It is a real-time multimodal interface into FRIDAY's existing core systems:

1. **Tool Execution & Authorization**:
   - When Gemini Live requests a tool execution via `LiveServerMessage.tool_call`:
   - Tool calls are routed directly through FRIDAY's `ToolRegistry` and `AutoApproveAuthorizer` / `BaseAuthorizer`.
   - Result outputs (and thought signatures where applicable) are sent back across the WebSocket via `session.send_tool_response(function_responses=...)`.
   - Gemini incorporates tool results and continues vocal generation seamlessly.
2. **Persistent Conversation Memory**:
   - Upon turn completion (`turn_complete=True`), the accumulated user transcription and agent output transcription are committed into `SQLiteConversationMemory`.
   - Memory auto-generates `gemini-embedding-2` embeddings for long-term recall.
3. **Semantic Memory Recall**:
   - Prior to session connection, relevant historical memories are retrieved via hybrid search and injected into the Live session `system_instruction`.

---

## 6. Security, Privacy & Token Management

1. **Local Desktop Architecture**:
   - FRIDAY runs as a secured local desktop application on Windows.
   - `FRIDAY_GEMINI_API_KEY` is loaded from the root `.env` into process memory with zero console logging or exception leakage.
2. **Future Ephemeral Token Strategy**:
   - For future distributed or mobile clients where the frontend does not run in a trusted local environment:
   - FRIDAY backend issues short-lived (10-minute) ephemeral session tokens via Google Cloud token exchange.
   - The client connects using the ephemeral token, never exposing master API keys.

---

## 7. Configuration Surface

| Setting Key | Default Value | Description |
| :--- | :--- | :--- |
| `FRIDAY_VOICE_ENABLED` | `false` | Master toggle (CLI starts in text mode by default; `/voice` enters live mode) |
| `FRIDAY_VOICE_PROVIDER` | `gemini` | Voice provider backend (`gemini` or `mock`) |
| `FRIDAY_VOICE_LIVE_MODEL` | `gemini-2.0-flash` | Gemini Live multimodal voice model |
| `FRIDAY_VOICE_INPUT_SAMPLE_RATE` | `16000` | Input PCM sample rate (Hz) |
| `FRIDAY_VOICE_LIVE_SAMPLE_RATE` | `24000` | Output PCM sample rate (Hz) |
| `FRIDAY_VOICE_PLAYBACK_BUFFER_MS` | `100` | Output audio buffering window |
| `FRIDAY_VOICE_LIVE_MAX_RETRIES` | `3` | Maximum WebSocket reconnect attempts on transient network disconnect |

---

## 8. Implementation Roadmap (Phase 5.2+)

1. **`src/friday/voice/live_session.py`**:
   - Implement `GeminiLiveVoiceSession` using `client.aio.live.connect`.
   - Full-duplex `asyncio` task architecture for audio capture, streaming, reception, playback, and tool invocation.
2. **`src/friday/voice/audio_io.py`**:
   - Continuous non-blocking microphone stream (`sounddevice.RawInputStream`).
   - Continuous non-blocking speaker stream (`sounddevice.RawOutputStream`) with instant purge on interruption.
3. **`src/friday/cli/main.py`**:
   - Connect `/voice` interactive command to launch the `GeminiLiveVoiceSession` on demand.
4. **Offline Mock & Integration Suite**:
   - Mock WebSocket session fixtures in `tests/test_live_voice.py` verifying full-duplex loops, interruption purges, and tool calls without hardware dependencies.
