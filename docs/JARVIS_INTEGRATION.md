# FRIDAY — J.A.R.V.I.S Capability Integration & Futuristic Desktop Architecture

## Overview

This document specifies the integration of desktop assistant capabilities inspired by [GauravSingh9356/J.A.R.V.I.S](https://github.com/GauravSingh9356/J.A.R.V.I.S) and the visual desktop experience from [Sagar Tamang](https://sagartamang.com/) into FRIDAY's enterprise architecture.

**Key Rule Maintained:**
FRIDAY remains the authoritative single source of truth. No secondary assistants, alternate memory silos, or brittle keyword parsers (`if "cmd" in query`) were introduced. Every capability is exposed as a validated, schema-driven tool in FRIDAY's cognitive loop under strict security and capability authorization.

---

## 1. Capability Mapping & Architecture Matrix

| Capability | J.A.R.V.I.S Approach | FRIDAY Unified Production Architecture |
|---|---|---|
| **Face Recognition** | Haar Cascade script with raw files (`trainer.yml`) | `FaceProfileManager` in `src/friday/security/face_biometrics.py` with multi-profile storage, normalized feature vectors, configurable threshold, and `VerifyFaceIdentityTool` / `EnrollFaceIdentityTool` gated by `AuthorizationManager`. |
| **Email** | Hardcoded SMTP script | Enhanced `SendEmailTool` (SENSITIVE gated) and `DraftEmailTool` (SAFE review) in `src/friday/tools/builtin/email_tools.py` with SMTP credentials managed via `.env`. |
| **News** | Single-source NewsAPI key | `NewsTool` in `src/friday/tools/builtin/news.py` using open XML RSS topic feeds (Google News/global) with category filtering and optional browser launch. |
| **Todo / Tasks** | Flat `data.txt` file | `SQLiteTaskStore` in `src/friday/persistence/task_store.py` and `ManageTasksTool` in `src/friday/tools/builtin/task_management.py` with priority, due date, status tracking, and SQLite ACID guarantees. |
| **Memory** | Ephemeral voice notes | `RememberFactTool` in `src/friday/tools/builtin/remember.py` storing explicit user preferences and notes into SQLite memory alongside `MemorySearchTool`. |
| **Website Launching** | Hardcoded `if 'open youtube' in query` | `OpenWebsiteTool` in `src/friday/tools/builtin/open_website.py` resolving natural names (YouTube, Google, GitHub, Amazon, Spotify, etc.) and arbitrary URLs to the default browser. |
| **YouTube** | Subprocess script | `YouTubeTool` in `src/friday/tools/builtin/youtube.py` searching videos and opening playback in the default browser. |
| **Maps & Location** | `geocoder` script | `LocationMapsTool` in `src/friday/tools/builtin/location_maps.py` providing network IP geolocation and Google Maps routing / place search. |
| **Weather** | Obsolete weather API key | `WeatherTool` in `src/friday/tools/builtin/weather.py` using Open-Meteo free API (WMO weather conditions, Celsius/Fahrenheit, wind speed, humidity, and rain probability). |
| **Wikipedia** | Python `wikipedia` print | `WikipediaTool` in `src/friday/tools/builtin/wikipedia_tool.py` using Wikipedia REST API with Opensearch fallback and canonical source citation. |
| **Dictionary** | Giant local `data.json` | `DictionaryTool` in `src/friday/tools/builtin/dictionary_tool.py` with Free Dictionary API definitions, phonetics, examples, and `difflib` spelling suggestions. |
| **Screenshot / Vision** | `pyautogui.screenshot()` | `ScreenSnapshotTool` in `src/friday/tools/builtin/screen_snapshot.py` with optional disk saving and multimodal vision analysis via `ScreenAnalyzer`. |
| **System Info & Power** | `psutil` print statements | `GetSystemResourcesTool` in `src/friday/tools/builtin/system_monitor.py` reporting CPU %, RAM %, top processes, and battery telemetry (`psutil.sensors_battery()`). |
| **Media Playback** | None / local files | `MediaControlTool` in `src/friday/tools/builtin/media_control.py` using Windows virtual key events (`VK_MEDIA_PLAY_PAUSE`, `VK_MEDIA_NEXT_TRACK`, `VK_VOLUME_UP`, etc.) and Spotify launching. |
| **Voice Interface** | Old synchronous `pyttsx3` / `speech_recognition` | Primary `GeminiLiveVoiceSession` in `src/friday/voice/gemini_live_session.py` with full-duplex 16 kHz input / 24 kHz output, Google Server-Side VAD, barge-in, and real-time state events. |

---

## 2. Desktop UI Architecture

The native desktop overlay (`friday --desktop` / `friday-desktop`) is built with PyQt6, providing a frameless, transparent, always-on-top companion inspired by Sagar Tamang's Iron Man HUD concept.

```
                  DesktopOverlay (PyQt6)
                            │
       ┌────────────────────┴────────────────────┐
       ▼                                         ▼
   FridayOrb                                 Chat Panel
  (9 Visual States)                     (Transcript & Input)
       │                                         │
       └────────────────────┬────────────────────┘
                            │
                      BackendWorker
                            │
       ┌────────────────────┴────────────────────┐
       ▼                                         ▼
  FridayAgent                         GeminiLiveVoiceSession
  (Cognitive Loop & Tools)            (Realtime Audio Engine)
```

### The 9 Visual Assistant States

1. **IDLE**: Holographic Cyan glowing orb with subtle breathing animation. Status: `SYSTEM IDLE`.
2. **LISTENING**: Emerald Green pulsating ripple when the microphone is capturing speech.
3. **THINKING**: Electric Purple spinning HUD arc indicating cognitive reasoning and plan formation.
4. **PLANNING**: Deep Azure Blue preparing multi-step action plans.
5. **EXECUTING**: Reactor Gold active spinning arc displaying the tool currently running (e.g., `Executing: open_application...`).
6. **CONFIRMATION**: Warning Amber pulsing orb displaying interactive `[Authorize]` and `[Cancel]` buttons for sensitive operations.
7. **SPEAKING**: Voice Orange responsive vocalization pulse synchronized with audio delivery.
8. **ERROR**: Alert Crimson warning banner with human-readable diagnostic error.
9. **DISCONNECTED**: Muted Steel Gray indicator with automatic reconnection attempt.

### Global Windows Hotkey
- **Shortcut:** `Ctrl + Shift + Space`
- **Behavior:** Registered via Windows native `RegisterHotKey` API (`WM_HOTKEY`). Summons or focuses FRIDAY from any desktop application without capturing audio until explicitly engaged.

---

## 3. Configuration & Security

All configuration options are defined in `friday.core.config.Settings` and driven by `.env`:

```bash
# Face Biometrics
FRIDAY_FACE_AUTH_ENABLED=true
FRIDAY_FACE_SIMILARITY_THRESHOLD=0.70
FRIDAY_FACE_PROFILE_DIR=data/face_profiles

# Desktop Companion
FRIDAY_DESKTOP_ENABLED=true
FRIDAY_DESKTOP_HOTKEY="Ctrl+Shift+Space"

# Outgoing Email (Optional SMTP credentials)
FRIDAY_EMAIL_ADDRESS="user@gmail.com"
FRIDAY_EMAIL_APP_PASSWORD="your-app-password"
FRIDAY_EMAIL_SMTP_HOST="smtp.gmail.com"
FRIDAY_EMAIL_SMTP_PORT=587
```

### Security & Safety Classification
- **SAFE Tools (Auto-Authorized):** `get_weather`, `get_news`, `wikipedia_summary`, `dictionary`, `manage_tasks`, `remember_fact`, `open_website`, `youtube`, `location_and_maps`, `media_control`, `get_system_resources`, `verify_face_identity`.
- **SENSITIVE Tools (Requires Authorization):** `send_email`, `enroll_face_identity`, `execute_command`, `screen_snapshot`.
- **DANGEROUS Tools (Explicit Confirmation & Audit):** `system_power_control` (shutdown/reboot), `file_operations` (delete).

---

## 4. Usage Instructions

### CLI Commands

```powershell
# Launch the futuristic desktop overlay
friday --desktop
# or
friday-desktop

# Start Gemini Live bidirectional real-time voice mode
friday --voice

# Start standard interactive CLI text conversation
friday

# Run system health checks
friday --doctor

# Verify registered action surface
friday --action-audit

# Start API server for web interface
friday --serve
```

### Example Natural Language Interactions

- **Tasks:** *"Add finish my project to my tasks"* ➔ *"What are my tasks today?"* ➔ *"Mark the project task complete"*
- **Weather:** *"What's the weather in Hyderabad?"* ➔ *"Will it rain today?"*
- **News:** *"What's today's top technology news?"*
- **Research:** *"Who was Alan Turing?"* ➔ *"Define recursion"* ➔ *"How do you spell accommodation?"*
- **Media & Apps:** *"Open YouTube and search for lofi beats"* ➔ *"Pause music"* ➔ *"Open GitHub"*
- **Location:** *"Where am I?"* ➔ *"Find coffee shops near me"*
- **Memory:** *"Remember that my flight is on Thursday at 4 PM"* ➔ *"What did I ask you to remember?"*
- **System Telemetry:** *"What's my battery level and CPU usage?"*
