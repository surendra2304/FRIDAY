# FRIDAY Desktop Overlay

FRIDAY now includes a native, dependency-light desktop shell for the voice-first experience: a compact always-on-top pill/orb that expands into a transcript and command panel.

## Launch

```powershell
friday --desktop
```

or, after installation:

```powershell
friday-desktop
```

## Interaction

- **Click the orb:** expand/collapse the assistant.
- **Double-click the orb / Listen:** start or stop the Gemini Live voice session.
- **Ctrl+Shift+Space (Windows):** expand/collapse the overlay globally.
- **Text box:** send typed commands through the existing FRIDAY agent.
- **Transcript:** shows user and FRIDAY turns from the live session.

## Architecture

The overlay is intentionally a shell rather than a second agent. It reuses:

- `FridayAgent` for reasoning, memory, tools, workflows, and authorization.
- `GeminiLiveVoiceSession` for full-duplex 16 kHz input / 24 kHz output voice.
- The existing tool registry and safety gates for computer control and other actions.

This keeps the existing FRIDAY intelligence intact while adding the always-available desktop interaction model.

## Privacy behavior

The desktop shell does **not** enable microphone capture merely by launching the UI. Voice capture begins only when the user starts the voice session.
