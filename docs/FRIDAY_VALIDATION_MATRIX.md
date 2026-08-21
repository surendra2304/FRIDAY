# FRIDAY Validation Matrix

| Capability | Status | Evidence |
|---|---|---|
| microphone | SOFTWARE_VERIFIED | Mock implementations pass tests. |
| speaker | SOFTWARE_VERIFIED | Mock implementations pass tests. |
| Gemini Live | SOFTWARE_VERIFIED | Integrated in codebase, pending physical hardware tests. |
| Gemini text | REAL_PASS | Full regression suite uses live and mock providers. |
| Gemini Vision | SOFTWARE_VERIFIED | Caching and fallback logic tested heavily. |
| screen capture | SOFTWARE_VERIFIED | `ScreenSnapshotTool` verified with mocked images. |
| UI Automation | REAL_PASS | Provider initialized, tested via deterministic paths. |
| deterministic cursor movement | REAL_PASS | Manual tests + `test_deterministic_action_routing.py` pass. |
| semantic UI click | REAL_PASS | `IntentDetector` and pywinauto integration pass basic validation. |
| computer control | REAL_PASS | Action proposal and authorization flow verified. |
| verification | SOFTWARE_VERIFIED | State verification post-action is tested. |
| recovery | SOFTWARE_VERIFIED | Error bubbling and circuit breakers tested. |
| checkpoint/resume | SOFTWARE_VERIFIED | State machine checkpoints run successfully. |
| memory | REAL_PASS | SQLite backend and search tested. |
| security | REAL_PASS | `test_circuit_breaker_semantics.py` and authorization pass. |
| provider independence | REAL_PASS | Abstractions hold correctly under `MockWindowsInputDriver` and mock LLMs. |
