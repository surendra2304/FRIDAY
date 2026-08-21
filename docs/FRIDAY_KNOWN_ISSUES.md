# FRIDAY Bug & Risk Register

| Issue ID | Severity | Component | File/Function | Description | Status | Workaround | Next Investigation |
|---|---|---|---|---|---|---|---|
| ISSUE-001 | Low | Vision | `vision/detector.py` | Multi-monitor absolute coordinates may require scaling adjustments on non-standard DPIs. | OPEN | Use standard 100% scaling if testing multi-monitor setups. | Investigate `GetDpiForMonitor` integration in WindowsNativeInputDriver. |
| ISSUE-002 | Medium | Security | `core/auth.py` | Highly permissive prompts might bypass intent detection for some destructive actions. | INVESTIGATING | Strict Authorization requirement acts as a final gate. | Enhance adversarial prompt rejection in the cognitive phase. |
| ISSUE-003 | Low | UI Automation | `ui_automation/provider.py` | Fuzzy matching might select incorrect elements if names are highly similar. | OPEN | User can fall back to deterministic coordinate clicks. | Refine difflib threshold and incorporate hierarchy context matching. |
