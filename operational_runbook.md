# FRIDAY — Operational Runbook & Production Guide

**Version**: 1.0.0 (Phase 10 Verified)  
**Target Environment**: Windows 10/11 x64, Python 3.11  
**Default Text / Vision Model**: `gemini-3.7-flash` (`thinking_level="medium"`)  
**Default Live Voice Model**: `gemini-3.1-flash-live-preview`  
**Security Posture**: Strictly Enforced (`Proposal != Execution`, Zero Credentials Persisted, Sanitized Checkpoints)

---

## 1. Quick Start & Initialization

### 1.1 Python Environment Setup
```powershell
# Verify Python 3.11
python --version

# Activate virtual environment if configured
.\.venv\Scripts\Activate.ps1

# Install / update project dependencies in editable mode
pip install -e ".[dev]"
```

### 1.2 Local Credential Configuration (.env)
Create a `.env` file in the root directory (`d:\FRIDAY\.env`).  
> **CRITICAL**: Never commit `.env` or hardcode API keys into tracked files. FRIDAY enforces strict pre-commit & secret-scan gates.

```env
# Production Gemini API Credentials (with Automatic Failover Pool)
FRIDAY_GEMINI_API_KEY=your_primary_api_key_here
FRIDAY_GEMINI_API_KEY_FALLBACK_1=your_fallback_1_key_here
FRIDAY_GEMINI_API_KEY_FALLBACK_2=your_fallback_2_key_here
FRIDAY_GEMINI_API_KEY_FALLBACK_3=your_fallback_3_key_here
FRIDAY_GEMINI_API_KEY_FALLBACK_4=your_fallback_4_key_here

# Runtime & Model Settings
FRIDAY_ENV=production
FRIDAY_AGENT_NAME=FRIDAY
FRIDAY_LOG_LEVEL=INFO
FRIDAY_ENABLE_AUTO_RECALL=true
```

---

## 2. Launching FRIDAY

### 2.1 Interactive Terminal / Voice Mode
```powershell
# Start FRIDAY agent CLI
python -m friday
```

### 2.2 Running Interactive Voice Diagnostic & Hardware Selection
```powershell
# Test microphone, speaker, and live turn-taking VAD
python -m friday.cli.voice_diag
```

---

## 3. Running Offline & Real-World Tests

### 3.1 Offline Test Suite (Zero Network / Quota-Free)
All unit and regression tests run completely offline using deterministic mock providers:
```powershell
# Run the entire offline test suite
pytest -q

# Run specific Phase test suites
pytest tests/test_phase9_acceptance_gate.py -v
pytest tests/test_system_reliability_fault_injection.py -v
pytest tests/test_adversarial_red_team.py -v
pytest tests/test_provider_independence.py -v
```

### 3.2 Controlled Real-World Integration Tests
```powershell
# Run real screen capture & vision verification (requires active credentials)
pytest tests/test_real_screen_understanding.py -v
```

---

## 4. Log Inspection & Troubleshooting

### 4.1 Log Files & Paths
- Application Logs: `logs/friday.log`
- Task Checkpoints: Stored in SQLite (`data/friday.db`) with sanitized memory buffers.
- Run Profiler:
  ```powershell
  python profile_performance.py
  ```

### 4.2 Handling Common Failure Modes
| Failure Symptom | Cause | Automatic Resolution | Manual Action |
| :--- | :--- | :--- | :--- |
| **HTTP 429 Quota Exhausted** | API rate limits reached | Instant failover across Fallback 1–4 keys; circuit breaker pauses embeddings. | Add fresh fallback keys in `.env` if all slots exhausted. |
| **Stale Screen Error** | UI element disappeared during proposal | Action preparer rejects execution and triggers replan. | Re-run perception or re-ground target element. |
| **Voice Barge-In** | User spoke while FRIDAY was acting | Task pauses cleanly and stores `VOICE_BARGE_IN` checkpoint. | Issue voice resume or let FRIDAY process the spoken override. |
| **GDI Capture Crash** | 32/64-bit ctypes alignment issue | Resolved in WindowsScreenCaptureProvider (GetDIBits argtypes configured). | Verify native desktop resolution in display settings. |

---

## 5. Git Synchronization & Pre-Commit Invariants

Before pushing changes to GitHub:
```powershell
# 1. Verify zero tracked .env files
git ls-files .env

# 2. Run automated security check
python security_check.py

# 3. Run full automated test suite
pytest -q

# 4. Verify clean status & push
git status --porcelain
git push origin main
```
