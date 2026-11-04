/**
 * FRIDAY Voice Control Module
 * Standalone ES6 class for voice interaction with FRIDAY dashboard
 * 
 * Usage in dashboard_n8n.html:
 *   <script src="voice_module.js"></script>
 *   <script>
 *     const voice = new VoiceControl({ basePath: BASE, getToken: ensureToken });
 *     voice.init();
 *   </script>
 */

class VoiceControl {
  /**
   * @param {Object} options
   * @param {string} options.basePath - Base path for API calls (e.g., "/friday" or "")
   * @param {Function} options.getToken - Async function that returns auth token
   * @param {Function} [options.onError] - Optional error callback
   * @param {Function} [options.onTranscript] - Optional interim transcript callback
   */
  constructor(options = {}) {
    this.basePath = options.basePath || "";
    this.getToken = options.getToken || (async () => "");
    this.onError = options.onError || ((msg) => console.error("[VoiceControl]", msg));
    this.onTranscript = options.onTranscript || (() => {});

    // DOM references (set in init)
    this.elements = {};

    // State
    this.recognition = null;
    this.listening = false;
    this.currentAudio = null;
    this.voiceMode = "execute"; // "execute" | "ask"
    this.speakReplies = true;

    // Constants
    this.STORAGE_KEYS = {
      voice: "friday.voice",
      sttLang: "friday.sttLang",
      voiceMode: "friday.voiceMode",
      speakReplies: "friday.speakReplies"
    };

    this.VOICES = {
      "en-IN-NeerjaNeural": { lang: "en", label: "English — Neerja" },
      "en-IN-PrabhatNeural": { lang: "en", label: "English — Prabhat" },
      "te-IN-ShrutiNeural": { lang: "te", label: "తెలుగు — Shruti" },
      "te-IN-MohanNeural": { lang: "te", label: "తెలుగు — Mohan" }
    };

    // Bind methods
    this._onResult = this._onResult.bind(this);
    this._onEnd = this._onEnd.bind(this);
    this._onError = this._onError.bind(this);
    this._onMicClick = this._onMicClick.bind(this);
    this._onSttLangChange = this._onSttLangChange.bind(this);
    this._onTtsVoiceChange = this._onTtsVoiceChange.bind(this);
    this._onModeChange = this._onModeChange.bind(this);
    this._onSpeakRepliesToggle = this._onSpeakRepliesToggle.bind(this);
  }

  /**
   * Initialize the voice control module
   * Must be called after DOM is ready
   */
  init() {
    this._cacheElements();
    this._setupSpeechRecognition();
    this._loadPreferences();
    this._bindEvents();
    this._syncUI();
  }

  /**
   * Start listening for voice input
   */
  startListening() {
    if (!this.recognition || this.listening) return;
    this.listening = true;
    this._updateVoiceUI(true);
    try {
      this.recognition.start();
    } catch (e) {
      this.listening = false;
      this._updateVoiceUI(false);
      this.onError("Failed to start recognition: " + e.message);
    }
  }

  /**
   * Stop listening for voice input
   */
  stopListening() {
    if (!this.recognition || !this.listening) return;
    this.listening = false;
    try {
      this.recognition.stop();
    } catch (e) {
      // Ignore
    }
    this._updateVoiceUI(false);
  }

  /**
   * Toggle listening state
   */
  toggleListening() {
    if (this.listening) {
      this.stopListening();
    } else {
      this.startListening();
    }
  }

  /**
   * Speak text using TTS endpoint
   * @param {string} text - Text to speak
   * @param {Object} [options] - Optional overrides
   * @param {string} [options.voice] - Override voice
   * @param {boolean} [options.force] - Force speak even if speakReplies is false
   */
  async speak(text, options = {}) {
    if (!text || (!this.speakReplies && !options.force)) return;

    try {
      const token = await this.getToken();
      if (!token) throw new Error("No auth token");

      let voice = options.voice || localStorage.getItem(this.STORAGE_KEYS.voice);
      if (!voice) {
        voice = this._isTeluguText(text) ? "te-IN-ShrutiNeural" : "en-IN-NeerjaNeural";
      }

      // Auto-select voice based on text language
      if (this._isTeluguText(text) && !voice.startsWith("te-")) {
        voice = "te-IN-ShrutiNeural";
      } else if (!this._isTeluguText(text) && voice.startsWith("te-")) {
        voice = "en-IN-NeerjaNeural";
      }

      localStorage.setItem(this.STORAGE_KEYS.voice, voice);

      this._setSpeakingState(true);

      const res = await fetch(this.basePath + "/api/voice/speak", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-FRIDAY-Control-Token": token
        },
        body: JSON.stringify({
          text,
          voice,
          lang: voice.startsWith("te-") ? "te" : "en"
        })
      });

      if (!res.ok) throw new Error("TTS " + res.status);

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);

      if (this.currentAudio) {
        this.currentAudio.pause();
        this.currentAudio.src = "";
      }

      this.currentAudio = new Audio(url);
      this.currentAudio.onended = () => {
        URL.revokeObjectURL(url);
        this._setSpeakingState(false);
      };
      this.currentAudio.onerror = () => {
        URL.revokeObjectURL(url);
        this._setSpeakingState(false);
      };

      await this.currentAudio.play();
    } catch (e) {
      this.onError("Speech output failed: " + e.message);
      this._setSpeakingState(false);
    }
  }

  /**
   * Set voice mode: "execute" or "ask"
   * @param {"execute"|"ask"} mode
   */
  setMode(mode) {
    if (mode !== "execute" && mode !== "ask") return;
    this.voiceMode = mode;
    localStorage.setItem(this.STORAGE_KEYS.voiceMode, mode);
    this._syncModeUI();
  }

  /**
   * Toggle speak replies setting
   * @param {boolean} [enabled] - Optional explicit value
   */
  toggleSpeakReplies(enabled) {
    this.speakReplies = enabled !== undefined ? enabled : !this.speakReplies;
    localStorage.setItem(this.STORAGE_KEYS.speakReplies, String(this.speakReplies));
    this._syncSpeakRepliesUI();
  }

  /**
   * Check if currently listening
   */
  isListening() {
    return this.listening;
  }

  /**
   * Check if currently speaking
   */
  isSpeaking() {
    return this.currentAudio && !this.currentAudio.paused;
  }

  /**
   * Get current voice mode
   */
  getMode() {
    return this.voiceMode;
  }

  /**
   * Clean up resources
   */
  destroy() {
    this.stopListening();
    if (this.recognition) {
      this.recognition.onresult = null;
      this.recognition.onend = null;
      this.recognition.onerror = null;
      this.recognition = null;
    }
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio = null;
    }
    this._unbindEvents();
  }

  // ==================== Private Methods ====================

  _cacheElements() {
    this.elements = {
      micBtn: document.getElementById("micBtn"),
      voiceStateTitle: document.getElementById("voiceStateTitle"),
      voiceStateSub: document.getElementById("voiceStateSub"),
      sttLang: document.getElementById("sttLang"),
      ttsVoice: document.getElementById("ttsVoice"),
      modeBtns: document.querySelectorAll("[data-voice-mode]"),
      speakRepliesToggle: document.getElementById("speakRepliesToggle")
    };
  }

  _setupSpeechRecognition() {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {
      if (this.elements.micBtn) {
        this.elements.micBtn.disabled = true;
        this.elements.micBtn.title = "Speech recognition not supported";
      }
      if (this.elements.voiceStateTitle) {
        this.elements.voiceStateTitle.textContent = "Voice not supported";
      }
      if (this.elements.voiceStateSub) {
        this.elements.voiceStateSub.textContent = "Use Chrome or Edge for voice commands";
      }
      return;
    }

    this.recognition = new SpeechRec();
    this.recognition.continuous = true;
    this.recognition.interimResults = true;
    this.recognition.lang = localStorage.getItem(this.STORAGE_KEYS.sttLang) || "en-IN";

    this.recognition.onresult = this._onResult;
    this.recognition.onend = this._onEnd;
    this.recognition.onerror = this._onError;
  }

  _loadPreferences() {
    // STT Language
    const savedSttLang = localStorage.getItem(this.STORAGE_KEYS.sttLang) || "en-IN";
    if (this.elements.sttLang) {
      this.elements.sttLang.value = savedSttLang;
    }
    if (this.recognition) {
      this.recognition.lang = savedSttLang;
    }

    // TTS Voice
    const savedVoice = localStorage.getItem(this.STORAGE_KEYS.voice) || "en-IN-NeerjaNeural";
    if (this.elements.ttsVoice) {
      this.elements.ttsVoice.value = savedVoice;
    }

    // Voice Mode
    this.voiceMode = localStorage.getItem(this.STORAGE_KEYS.voiceMode) || "execute";

    // Speak Replies
    const savedSpeakReplies = localStorage.getItem(this.STORAGE_KEYS.speakReplies);
    this.speakReplies = savedSpeakReplies !== "false"; // default true
  }

  _bindEvents() {
    if (this.elements.micBtn) {
      this.elements.micBtn.addEventListener("click", this._onMicClick);
    }
    if (this.elements.sttLang) {
      this.elements.sttLang.addEventListener("change", this._onSttLangChange);
    }
    if (this.elements.ttsVoice) {
      this.elements.ttsVoice.addEventListener("change", this._onTtsVoiceChange);
    }
    this.elements.modeBtns.forEach(btn => {
      btn.addEventListener("click", this._onModeChange);
    });
    if (this.elements.speakRepliesToggle) {
      this.elements.speakRepliesToggle.addEventListener("change", this._onSpeakRepliesToggle);
    }
  }

  _unbindEvents() {
    if (this.elements.micBtn) {
      this.elements.micBtn.removeEventListener("click", this._onMicClick);
    }
    if (this.elements.sttLang) {
      this.elements.sttLang.removeEventListener("change", this._onSttLangChange);
    }
    if (this.elements.ttsVoice) {
      this.elements.ttsVoice.removeEventListener("change", this._onTtsVoiceChange);
    }
    this.elements.modeBtns.forEach(btn => {
      btn.removeEventListener("click", this._onModeChange);
    });
    if (this.elements.speakRepliesToggle) {
      this.elements.speakRepliesToggle.removeEventListener("change", this._onSpeakRepliesToggle);
    }
  }

  _syncUI() {
    this._syncModeUI();
    this._syncSpeakRepliesUI();
    this._updateVoiceUI(false);
  }

  _syncModeUI() {
    this.elements.modeBtns.forEach(btn => {
      const isActive = btn.dataset.voiceMode === this.voiceMode;
      btn.classList.toggle("active", isActive);
      btn.setAttribute("aria-pressed", String(isActive));
    });
  }

  _syncSpeakRepliesUI() {
    if (this.elements.speakRepliesToggle) {
      this.elements.speakRepliesToggle.checked = this.speakReplies;
    }
  }

  _onMicClick() {
    this.toggleListening();
  }

  _onSttLangChange() {
    const lang = this.elements.sttLang.value;
    localStorage.setItem(this.STORAGE_KEYS.sttLang, lang);
    if (this.recognition) {
      try {
        this.recognition.lang = lang;
        if (this.listening) {
          this.recognition.stop();
          this.recognition.start();
        }
      } catch (e) {
        this.onError("Failed to change STT language: " + e.message);
      }
    }
  }

  _onTtsVoiceChange() {
    const voice = this.elements.ttsVoice.value;
    localStorage.setItem(this.STORAGE_KEYS.voice, voice);
  }

  _onModeChange(e) {
    const mode = e.currentTarget.dataset.voiceMode;
    this.setMode(mode);
  }

  _onSpeakRepliesToggle(e) {
    this.toggleSpeakReplies(e.target.checked);
  }

  _onResult(ev) {
    let interim = "";
    for (let i = ev.resultIndex; i < ev.results.length; i++) {
      const res = ev.results[i];
      if (res.isFinal) {
        const finalText = res[0].transcript.trim();
        if (finalText) {
          this._handleVoiceCommand(finalText);
        }
      } else {
        interim += res[0].transcript;
      }
    }
    if (interim) {
      this.onTranscript(interim);
      if (this.elements.voiceStateSub) {
        this.elements.voiceStateSub.textContent = interim;
      }
    }
  }

  _onEnd() {
    if (this.listening) {
      try {
        this.recognition.start();
      } catch (e) {
        this.listening = false;
        this._updateVoiceUI(false);
      }
    } else {
      this._updateVoiceUI(false);
    }
  }

  _onError(ev) {
    this.listening = false;
    this._updateVoiceUI(false);

    switch (ev.error) {
      case "not-allowed":
        this.onError("Microphone access denied");
        break;
      case "audio-capture":
        this.onError("Microphone not available");
        break;
      case "service-not-allowed":
        this.onError("Speech service blocked");
        break;
      case "no-speech":
        // Silent - just restart if still listening
        break;
      default:
        this.onError("Speech recognition error: " + ev.error);
    }
  }

  _updateVoiceUI(isListening) {
    const btn = this.elements.micBtn;
    const title = this.elements.voiceStateTitle;
    const sub = this.elements.voiceStateSub;

    if (!btn || !title || !sub) return;

    if (isListening) {
      btn.classList.add("listening");
      btn.style.borderColor = "var(--mint)";
      btn.style.boxShadow = "0 0 0 6px rgba(124,240,184,.15)";
      title.textContent = "Listening...";
      title.className = "speaking";
      sub.textContent = "Speak your command in English or Telugu";
    } else {
      btn.classList.remove("listening");
      btn.style.borderColor = "";
      btn.style.boxShadow = "";
      title.textContent = "Talk to FRIDAY";
      title.className = "idle";
      sub.textContent = "Click mic, speak in English or Telugu";
    }
  }

  _setSpeakingState(isSpeaking) {
    const title = this.elements.voiceStateTitle;
    const sub = this.elements.voiceStateSub;

    if (!title || !sub) return;

    if (isSpeaking) {
      title.textContent = "Speaking...";
      title.className = "speaking";
      sub.textContent = "";
    } else {
      title.textContent = "Talk to FRIDAY";
      title.className = "idle";
      sub.textContent = "Click mic, speak in English or Telugu";
    }
  }

  _isTeluguText(text) {
    return /[\u0C00-\u0C7F]/.test(text);
  }

  async _handleVoiceCommand(text) {
    const cleanText = text.trim();
    if (!cleanText) return;

    this.stopListening();

    // Show toast via global if available, otherwise console
    this._showToast("Processing: " + cleanText.slice(0, 50) + "...");
    await this.speak("Working on it.", { force: true });

    try {
      if (this.voiceMode === "execute") {
        await this._executeMode(cleanText);
      } else {
        await this._askMode(cleanText);
      }
    } catch (e) {
      this._showToast("Voice command failed: " + e.message, "bad");
      await this.speak("Sorry, that didn't work. " + e.message, { force: true });
    }
  }

  async _executeMode(text) {
    const token = await this.getToken();
    if (!token) throw new Error("No auth token");

    // Submit as autonomous goal
    const res = await fetch(this.basePath + "/api/autonomous/goals", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-FRIDAY-Control-Token": token
      },
      body: JSON.stringify({ goal: text, priority: 10 })
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || err.error || "Failed to create goal");
    }

    const data = await res.json();
    const goalId = data.goal_id;

    this._showToast("Mission started. Watch the graph.");

    // Switch to graph view if possible
    const graphLink = document.querySelector('[data-view="graph"]');
    if (graphLink) graphLink.click();

    // Poll for completion
    this._pollGoal(goalId);
  }

  async _askMode(text) {
    const token = await this.getToken();
    if (!token) throw new Error("No auth token");

    const res = await fetch(this.basePath + "/api/command", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-FRIDAY-Control-Token": token
      },
      body: JSON.stringify({ command: text })
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || err.error || "Command failed");
    }

    const data = await res.json();
    const answer = data.reply || "I heard you, but I don't have an answer yet.";

    this._showToast(answer.slice(0, 80));
    await this.speak(answer);
  }

  _pollGoal(goalId) {
    const poll = async () => {
      try {
        const token = await this.getToken();
        if (!token) throw new Error("No auth token");

        const res = await fetch(this.basePath + "/api/autonomous/goals/" + goalId, {
          headers: { "X-FRIDAY-Control-Token": token }
        });

        if (!res.ok) throw new Error("Poll failed");

        const goal = await res.json();

        if (goal) {
          // Trigger graph update if renderFriday is available globally
          if (window.renderFriday && goal.steps) {
            window.renderFriday(goal.steps);
          }

          if (goal.status === "COMPLETED" || goal.status === "PARTIAL" || goal.status === "FAILED") {
            const summary = goal.summary || "Done.";
            this._showToast(summary.slice(0, 100));
            await this.speak(summary);
            return;
          }
        }
        setTimeout(poll, 2000);
      } catch (e) {
        setTimeout(poll, 2000);
      }
    };
    poll();
  }

  _showToast(msg, type = "good") {
    // Try to use global showToast if available
    if (window.showToast) {
      window.showToast(msg, type);
      return;
    }

    // Fallback: create toast element
    let toast = document.getElementById("toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "toast";
      toast.setAttribute("role", "status");
      toast.setAttribute("aria-live", "polite");
      toast.style.cssText = `
        position:fixed;right:20px;bottom:20px;z-index:110;
        max-width:min(420px,calc(100% - 40px));
        border:1px solid #2b5f4b;border-radius:11px;
        background:#0b1d17;color:#d7f6e8;
        padding:11px 14px;font-size:12px;line-height:1.5;
        box-shadow:0 18px 44px rgba(0,0,0,.45);
        transform:translateY(12px);opacity:0;pointer-events:none;
        transition:.3s cubic-bezier(.16,1,.3,1)
      `;
      document.body.appendChild(toast);
    }

    const colors = {
      good: { border: "#2b5f4b", bg: "#0b1d17", color: "#d7f6e8" },
      bad: { border: "#5c2c2c", bg: "#1d1010", color: "#ffc9c9" },
      warn: { border: "#4d4026", bg: "#171307", color: "#f4dca6" }
    };
    const c = colors[type] || colors.good;
    toast.style.borderColor = c.border;
    toast.style.background = c.bg;
    toast.style.color = c.color;
    toast.textContent = msg;
    toast.classList.add("show");
    setTimeout(() => toast.classList.remove("show"), 3000);
  }
}

// Export for module systems
if (typeof module !== "undefined" && module.exports) {
  module.exports = VoiceControl;
}

// Export for global usage
if (typeof window !== "undefined") {
  window.VoiceControl = VoiceControl;
}