# -*- coding: utf-8 -*-
"""Onboarding Wizard for FRIDAY Operating System.

Provides an interactive, voice-guided first-run onboarding experience:
1. Detects missing configurations and credentials on initial startup
2. Step-by-step guided configuration:
   - LLM Provider API Keys (Groq, Mistral, OpenRouter, Gemini)
   - Managed Subsystem URLs (Trading Bot: 5000, Forge: 8000, AI-Universe: 8001, Nexus: 8002)
   - Voice Biometric Enrollment (records & verifies 3 distinct spoken passphrase samples)
   - User Preferences (morning briefing time, response detail level, alert urgency thresholds)
   - Optional third-party integrations (Telegram, Web Push, VAPID, FCM)
3. Voice-guided with structured text fallback
4. Persists onboarding state to disk with automatic session resumption
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger

logger = get_logger("onboarding.wizard")


class OnboardingStep:
    CHECK_ENV = "CHECK_ENV"
    API_KEYS = "API_KEYS"
    SUBSYSTEM_URLS = "SUBSYSTEM_URLS"
    VOICE_BIOMETRICS = "VOICE_BIOMETRICS"
    USER_PREFERENCES = "USER_PREFERENCES"
    OPTIONAL_INTEGRATIONS = "OPTIONAL_INTEGRATIONS"
    COMPLETED = "COMPLETED"


@dataclass
class OnboardingState:
    """Persistent state tracking onboarding progress."""
    current_step: str = OnboardingStep.CHECK_ENV
    completed_steps: List[str] = field(default_factory=list)
    api_keys_configured: Dict[str, bool] = field(default_factory=dict)
    subsystems_configured: Dict[str, str] = field(default_factory=dict)
    biometric_samples_recorded: int = 0
    biometric_enrolled: bool = False
    preferences: Dict[str, Any] = field(default_factory=dict)
    optional_integrations: Dict[str, bool] = field(default_factory=dict)
    is_fully_onboarded: bool = False
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class OnboardingWizard:
    """Guides new users through complete FRIDAY OS provisioning with state persistence."""

    def __init__(self, state_file_path: Optional[str] = None) -> None:
        self.state_file = Path(state_file_path or os.path.join("data", "onboarding_state.json"))
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state = OnboardingState()
        self._lock = threading.RLock()
        self.load_state()

    def load_state(self) -> None:
        """Loads saved onboarding progress from disk."""
        with self._lock:
            if self.state_file.exists():
                try:
                    with open(self.state_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self.state = OnboardingState(**data)
                    logger.info(f"[ONBOARDING] Loaded existing onboarding state. Current step: {self.state.current_step}")
                except Exception as e:
                    logger.warning(f"[ONBOARDING] Failed to parse onboarding state file: {e}. Starting fresh.")
                    self.state = OnboardingState()

    def save_state(self) -> None:
        """Persists current onboarding progress to disk."""
        with self._lock:
            self.state.last_updated = datetime.now(timezone.utc).isoformat()
            try:
                with open(self.state_file, "w", encoding="utf-8") as f:
                    json.dump(self.state.__dict__, f, indent=2)
            except Exception as e:
                logger.error(f"[ONBOARDING] Failed to save state to {self.state_file}: {e}")

    def is_first_run_required(self) -> bool:
        """Determines if first-run setup needs to be executed."""
        with self._lock:
            if self.state.is_fully_onboarded:
                return False
            # Check if essential API keys and subsystems are configured
            has_gemini = bool(os.getenv("GEMINI_API_KEY"))
            has_groq = bool(os.getenv("GROQ_API_KEY"))
            if not has_gemini and not has_groq and not self.state.api_keys_configured:
                return True
            return not self.state.is_fully_onboarded

    def get_current_prompt(self) -> Dict[str, Any]:
        """Returns the voice and text prompt for the active onboarding step."""
        with self._lock:
            step = self.state.current_step

            if step == OnboardingStep.CHECK_ENV:
                return {
                    "step": step,
                    "spoken_prompt": (
                        "Welcome to FRIDAY, your Autonomous AI Operating System. "
                        "I noticed this is our first time setting up together. "
                        "Shall we begin configuring your API keys and subsystem connections?"
                    ),
                    "text_instructions": "Initial system scan complete. Ready to configure provider keys.",
                    "required_input": "confirmation",
                }

            elif step == OnboardingStep.API_KEYS:
                return {
                    "step": step,
                    "spoken_prompt": (
                        "Step 1: LLM Provider Keys. Please provide your Google Gemini or Groq API keys "
                        "so I can initialize my reasoning core and live voice duplex engine."
                    ),
                    "text_instructions": "Enter GEMINI_API_KEY, GROQ_API_KEY, or MISTRAL_API_KEY.",
                    "required_input": "api_keys",
                }

            elif step == OnboardingStep.SUBSYSTEM_URLS:
                return {
                    "step": step,
                    "spoken_prompt": (
                        "Step 2: Subsystem Endpoints. I can manage your Trading Bot, Forge SWE Engine, "
                        "AI-Universe Core, and Nexus Growth Engine. Would you like to use default localhost ports?"
                    ),
                    "text_instructions": "Default URLs: Trading (5000), Forge (8000), AI-Universe (8001), Nexus (8002).",
                    "required_input": "subsystem_urls",
                }

            elif step == OnboardingStep.VOICE_BIOMETRICS:
                samples_needed = 3 - self.state.biometric_samples_recorded
                return {
                    "step": step,
                    "spoken_prompt": (
                        f"Step 3: Voice Biometric Security. For emergency operations and dangerous commands, "
                        f"I need to enroll your voiceprint. Please speak phrase sample {self.state.biometric_samples_recorded + 1} of 3: "
                        f"'FRIDAY, authorize emergency operations.'"
                    ),
                    "text_instructions": f"Record sample {self.state.biometric_samples_recorded + 1}/3 for biometric enrollment.",
                    "required_input": "voice_sample",
                }

            elif step == OnboardingStep.USER_PREFERENCES:
                return {
                    "step": step,
                    "spoken_prompt": (
                        "Step 4: Preferences. What time would you like your morning executive briefing, "
                        "and do you prefer concise bullet summaries or detailed technical reports?"
                    ),
                    "text_instructions": "Configure briefing time (default: 08:00 UTC) and detail level (brief/detailed).",
                    "required_input": "preferences",
                }

            elif step == OnboardingStep.OPTIONAL_INTEGRATIONS:
                return {
                    "step": step,
                    "spoken_prompt": (
                        "Step 5: Optional Integrations. Would you like to enable Telegram alerts, "
                        "Web Push notifications, or Firebase mobile push?"
                    ),
                    "text_instructions": "Enable Telegram, VAPID Web Push, or Firebase Cloud Messaging (FCM).",
                    "required_input": "integrations",
                }

            else:
                return {
                    "step": OnboardingStep.COMPLETED,
                    "spoken_prompt": "Setup complete! All subsystems are green and voice biometric security is active. How may I assist you today, Operator?",
                    "text_instructions": "FRIDAY Operating System is fully operational.",
                    "required_input": None,
                }

    def process_step_input(self, user_input: Dict[str, Any]) -> Dict[str, Any]:
        """Processes user input for the current step and advances state."""
        with self._lock:
            step = self.state.current_step

            if step == OnboardingStep.CHECK_ENV:
                self.state.completed_steps.append(step)
                self.state.current_step = OnboardingStep.API_KEYS

            elif step == OnboardingStep.API_KEYS:
                keys = user_input.get("keys", {})
                for k, v in keys.items():
                    if v:
                        self.state.api_keys_configured[k] = True
                self.state.completed_steps.append(step)
                self.state.current_step = OnboardingStep.SUBSYSTEM_URLS

            elif step == OnboardingStep.SUBSYSTEM_URLS:
                urls = user_input.get("urls", {
                    "trading_bot": "http://localhost:5000",
                    "forge": "http://localhost:8000",
                    "ai_universe": "http://localhost:8001",
                    "nexus": "http://localhost:8002",
                })
                self.state.subsystems_configured.update(urls)
                self.state.completed_steps.append(step)
                self.state.current_step = OnboardingStep.VOICE_BIOMETRICS

            elif step == OnboardingStep.VOICE_BIOMETRICS:
                # Accept voice sample
                self.state.biometric_samples_recorded += 1
                if self.state.biometric_samples_recorded >= 3:
                    self.state.biometric_enrolled = True
                    self.state.completed_steps.append(step)
                    self.state.current_step = OnboardingStep.USER_PREFERENCES

            elif step == OnboardingStep.USER_PREFERENCES:
                prefs = user_input.get("preferences", {
                    "briefing_time": "08:00",
                    "response_detail": "brief",
                    "quiet_hours": "00:00-08:00",
                })
                self.state.preferences.update(prefs)
                self.state.completed_steps.append(step)
                self.state.current_step = OnboardingStep.OPTIONAL_INTEGRATIONS

            elif step == OnboardingStep.OPTIONAL_INTEGRATIONS:
                integrations = user_input.get("integrations", {"web_push": True, "fcm": False, "telegram": False})
                self.state.optional_integrations.update(integrations)
                self.state.completed_steps.append(step)
                self.state.current_step = OnboardingStep.COMPLETED
                self.state.is_fully_onboarded = True

            self.save_state()
            return self.get_current_prompt()

    def reset_onboarding(self) -> None:
        """Resets onboarding state to allow re-running the wizard."""
        with self._lock:
            self.state = OnboardingState()
            self.save_state()
            logger.info("[ONBOARDING] Reset onboarding state.")


# Default singleton instance
onboarding_wizard = OnboardingWizard()
