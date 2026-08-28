# 📘 FRIDAY Production Operations Runbook

This runbook serves as the authoritative operational manual for deploying, monitoring, maintaining, troubleshooting, and recovering the **FRIDAY Autonomous AI Operating System** and its five managed subsystems (**Algorithmic Trading Bot**, **AI-Universe Intelligence Provider**, **FORGE Software Engineering Engine**, **Nexus Website & Growth Engine**, and **Sentinel Autonomous Security Engine**).

---

## 📋 1. Daily Operations Checklist

### Morning Routine (08:00 UTC)
1. **Executive Briefing**:
   - Voice trigger: *"Morning briefing"* or review the automated markdown report in `reports/ecosystem/`.
   - Verify portfolio equity, active positions, and overnight P&L across Binance, Bybit, and OKX.
   - Review high-intent enterprise leads detected by Nexus and assign follow-up tasks.
   - Inspect FORGE build queue and verify mean test coverage ($>90\%$) of completed packages.
   - Check **Sentinel Security Posture** (Overall Score $\ge 85$, zero unmitigated `CRITICAL` findings).
2. **Subsystem Health Verification**:
   - Speak *"What's the health of my systems?"* to execute parallel socket and telemetry audits across all 6 subsystems.
   - Verify all persistent operators are in `RUNNING` state.
3. **Pending Approvals & Alerts Review**:
   - Speak *"Security status"* and review any pending `HIGH_IMPACT` Sentinel dynamic verification actions.
   - Speak *"Any pending approvals?"* to audit Nexus and Forge workflow hold gates.

### Intraday Monitoring
1. Check ecosystem web dashboard at `/dashboard` or mobile touch view at `/mobile`.
2. Inspect active visitor intent scores and conversion anomaly warnings in Nexus.
3. Review any pending advisory recommendations from AI-Universe.
4. Monitor Sentinel Vigilance Operator alerts for new critical or high vulnerability discoveries.

### Evening Routine (20:00 UTC)
1. **Performance Wrap-Up**:
   - Speak *"Evening wrap-up"* to review realized daily P&L, software packages delivered, visitor volume, and perimeter security status.
2. **Backup Verification**:
   - Confirm periodic 6-hour backup snapshot creation in `backups/friday/`.

---

## 🛠️ 2. Weekly & Monthly Maintenance Procedures

### Weekly Maintenance (Sunday Evening)
- **Log Rotation & Archiving**: Rotate and compress active logs in `logs/` to prevent disk bloat.
- **Backup Snapshot Restoration Audit**: Run mock restoration of the latest snapshot in a scratch directory:
  ```python
  from friday.core.backup_recovery import backup_recovery_manager
  snapshots = backup_recovery_manager.list_snapshots()
  latest_id = snapshots[0]["snapshot_id"]
  backup_recovery_manager.restore_snapshot(latest_id)
  ```
- **Security Scan Review & Attack Surface Audit**: Speak *"Show me the attack surface"* to audit mapped perimeter routes and choke points.
- **Memory Compaction & Profiling**: Run `FridayDoctorEnhanced` memory diagnostics to verify zero object leaks and enforce episodic memory compaction.

### Monthly Maintenance
- **Strategy Performance Review**: Compute Sharpe ratio ($>2.0$), Sortino ratio ($>2.5$), and maximum drawdown ($\le 5.0\%$).
- **API Token Cost Analysis**: Audit total token expenditure across LLM providers (Groq, Mistral, OpenRouter, Gemini).
- **Security Posture Trend Review**: Audit monthly security index progression ($0-100$) and inspect credential rotation history.
- **Biometric & Lockout Audit**: Verify 15-minute biometric lockout telemetry and Fernet key integrity.

---

## 🚨 3. Emergency Operating Procedures & Kill Switches

### Emergency Procedure 1: Master Ecosystem-Wide Emergency Halt
- **Voice Command**: *"Emergency stop everything"* (Requires voice biometric $>0.95$ + spoken phrase *"Confirm emergency halt"*).
- **Cascade Sequence**:
  1. **Trading Bot**: Flattens all open positions and stops trading loop.
  2. **Nexus**: Pauses all active workflows and freezes agent actions.
  3. **Forge**: Checkpoints active tasks to disk and halts compiler pipelines.
  4. **Sentinel**: Terminates all active security scans, kills running assessment tasks, and holds approvals.
  5. **AI-Universe**: Switches consumers to last-known-good static parameters.
  6. **FRIDAY Operators**: Pauses all autonomous background operators; health monitoring remains **ACTIVE**.
- **Broadcast**: Dispatches red emergency banner across web and mobile interfaces.
- **Resumption**: Bulk resume is strictly prohibited. Each subsystem requires individual un-halt confirmation:
  ```python
  from friday.ecosystem.emergency_controller import master_emergency_controller
  master_emergency_controller.resume_subsystem("trading_bot", confirmation_token="auth_token_123")
  master_emergency_controller.resume_subsystem("sentinel", confirmation_token="auth_token_456")
  ```

### Emergency Procedure 2: Trading Bot Panic Halt
- **Voice Command**: *"Emergency stop trading"* (Requires confirmation token).
- **Target Latency**: $< 1.0\text{s}$ execution.

### Emergency Procedure 3: Cascade Failure Isolation
- When AI-Universe or Sentinel degrades, `CascadeFailureDetector` automatically isolates the provider and switches dependent subsystems (Forge, Nexus) to local rule fallbacks. Reconnects automatically once latency $< 1000\text{ms}$ and data freshness is verified.

---

## 🔍 4. Subsystem Troubleshooting & Port Reference

| Subsystem | Port | Default URL | Common Issue | Diagnostic & Automated Healing |
| :--- | :--- | :--- | :--- | :--- |
| **Trading Bot** | `5000` | `http://localhost:5000` | Socket timeout / Disconnection | `FridayDoctorEnhanced` auto-reconnects socket; verify exchange API keys in `.env`. |
| **FORGE Engine** | `8000` | `http://localhost:8000` | Build task loop / High CPU | Cancel task via `ForgeManagerSkill.cancel_task(task_id)`; run `PLAYBOOK:forge_runaway`. |
| **AI-Universe** | `8001` | `http://localhost:8001` | LLM rate limit / 500s | Multi-model failover auto-switches across 7 providers; fallback to rule advisory. |
| **Nexus Growth** | `8002` | `http://localhost:8002` | Conversion drop / 503 error | Run `PLAYBOOK:website_down`; check deploy correlation and execute rollback. |
| **Sentinel Security** | `8003` | `http://localhost:8003` | Scan queue timeout / Stale token | Run `PLAYBOOK:data_breach`; verify scope enforcement in `SentinelManagerSkill`. |
| **FRIDAY Core** | `9000` | `http://localhost:9000` | Voice session audio stutter | Rotate Gemini API keys in `GeminiCredentialPool`; restart `MicrophoneStream`. |

---

## 👥 5. Incident Escalation Matrix

```
Level 1: Nominal (Automated Resolution)
  └── Trigger: Transient socket timeout, single compilation retry.
  └── Action: FridayDoctorEnhanced heals socket / restarts worker automatically.

Level 2: Warning (Operator Notification)
  └── Trigger: Drawdown > 2.0%, Nexus conversion drop > 20%, high security vulnerability, unacted alerts > 24h.
  └── Action: Dispatches HIGH push notification & voice prompt to Surendra.

Level 3: Critical (Biometric Gated Emergency)
  └── Trigger: Drawdown breach > 3.0%, website 503 outage, critical SQLi/RCE vulnerability, cascading provider failure.
  └── Action: MasterEmergencyController 6-system halt / EmergencyPlaybooks automated execution.
```

---

## 🔐 6. Full Environment Configuration Reference

```bash
# Security & Credentials
FRIDAY_CREDENTIAL_ENCRYPTION_KEY=<base64_32_bytes_fernet_key>
FRIDAY_SECURITY_LOCKOUT_MINUTES=15
FRIDAY_MAX_FAILED_BIOMETRIC_ATTEMPTS=5

# Managed Subsystem URLs
TRADING_BOT_BASE_URL=http://localhost:5000
FORGE_BASE_URL=http://localhost:8000
AI_UNIVERSE_BASE_URL=http://localhost:8001
NEXUS_BASE_URL=http://localhost:8002
SENTINEL_BASE_URL=http://localhost:8003

# Environment & Performance
FRIDAY_ENV=production
FRIDAY_LOG_LEVEL=INFO
FRIDAY_STARTUP_TIMEOUT_SECONDS=10.0
FRIDAY_VOICE_LATENCY_MAX_MS=500.0
FRIDAY_RATE_LIMIT_PER_MINUTE=100
FRIDAY_QUIET_HOURS_START=22
FRIDAY_QUIET_HOURS_END=7
```
