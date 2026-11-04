/**
 * FRIDAY Voice Interaction System
 * Core voice interface for the FRIDAY Universe
 * 
 * Features:
 * - SpeechRecognition with continuous, interim results, auto language detect (en/te)
 * - SpeechSynthesis via /api/voice/speak with 4 voices (Neerja/Prabhat/Shruti/Mohan)
 * - Auto voice selection: Telugu text → te- voice, English → en- voice
 * - Single mode: User speaks → Friday processes → Friday executes → Friday speaks reply
 * - Real-time waveform visualization while listening
 * - Typing animation for interim results
 * - Lip-sync events for 3D character
 * - Settings persisted in localStorage (voice, language, speakReplies)
 * - WebSocket integration for real-time agent updates
 */

export class FridayVoice {
  /**
   * @param {Object} options
   * @param {string} options.basePath - Base path for API calls (e.g., "/friday" or "")
   * @param {Function} options.getToken - Async function that returns auth token
   * @param {Function} [options.onError] - Optional error callback
   * @param {Function} [options.onResult] - Optional final result callback
   * @param {Function} [options.onInterim] - Optional interim transcript callback
   * @param {Function} [options.onStateChange] - Optional state change callback
   * @param {HTMLElement} [options.waveformCanvas] - Canvas element for waveform visualization
   * @param {Object} [options.character] - FridayCharacter instance for lip-sync
   * @param {string} [options.wsUrl] - WebSocket URL for real-time updates
   */
  constructor(options = {}) {
    this.basePath = options.basePath || "";
    this.getToken = options.getToken || (async () => "");
    this.onError = options.onError || ((msg) => console.error("[FridayVoice]", msg));
    this.onResultCallback = options.onResult || (() => {});
    this.onInterimCallback = options.onInterim || (() => {});
    this.onStateChangeCallback = options.onStateChange || (() => {});
    this.waveformCanvas = options.waveformCanvas || null;
    this.character = options.character || null;
    this.wsUrl = options.wsUrl || null;

    // Voice configuration - 4 voices
    this.VOICES = {
      "en-IN-NeerjaNeural": { lang: "en", label: "English — Neerja", gender: "Female" },
      "en-IN-PrabhatNeural": { lang: "en", label: "English — Prabhat", gender: "Male" },
      "te-IN-ShrutiNeural": { lang: "te", label: "తెలుగు — Shruti", gender: "Female" },
      "te-IN-MohanNeural": { lang: "te", label: "తెలుగు — Mohan", gender: "Male" }
    };

    // State
    this.recognition = null;
    this.listening = false;
    this.processing = false;
    this.speaking = false;
    this.currentAudio = null;
    this.speakReplies = true;
    this.selectedVoice = "en-IN-NeerjaNeural";
    this.sttLang = "en-IN";
    this.autoLanguageDetect = true;
    
    // WebSocket
    this.ws = null;
    this.wsReconnectAttempts = 0;
    this.maxWsReconnectAttempts = 5;
    this.wsReconnectDelay = 1000;

    // Waveform visualization
    this.audioContext = null;
    this.analyser = null;
    this.microphone = null;
    this.waveformAnimationId = null;
    this.waveformData = new Uint8Array(256);
    this.waveformHistory = [];

    // Typing animation
    this.typingAnimationId = null;
    this.currentInterimText = "";
    this.displayedInterimText = "";

    // Lip-sync
    this.lipSyncEnabled = true;
    this.lastLipSyncTime = 0;

    // Storage keys
    this.STORAGE_KEYS = {
      voice: "friday.voice",
      sttLang: "friday.sttLang",
      speakReplies: "friday.speakReplies",
      autoLanguageDetect: "friday.autoLanguageDetect"
    };

    // Bind methods
    this._onResult = this._onResult.bind(this);
    this._onEnd = this._onEnd.bind(this);
    this._onError = this._onError.bind(this);
    this._onAudioProcess = this._onAudioProcess.bind(this);
  }

  /**
   * Initialize the voice system
   * Must be called after DOM is ready
   */
  async init() {
    this._loadPreferences();
    this._setupSpeechRecognition();
    this._setupAudioContext();
    this._setupWaveformCanvas();
    this._connectWebSocket();
    this._emitStateChange("initialized");
    return this;
  }

  /**
   * Start listening for voice input
   */
  startListening() {
    if (!this.recognition || this.listening || this.processing) return;
    
    this.listening = true;
    this.processing = false;
    this._emitStateChange("listening");
    
    try {
      this.recognition.start();
      this._startWaveformVisualization();
      this._startTypingAnimation();
    } catch (e) {
      this.listening = false;
      this._emitStateChange("idle");
      this.onError("Failed to start recognition: " + e.message);
    }
  }

  /**
   * Stop listening for voice input
   */
  stopListening() {
    if (!this.recognition || !this.listening) return;
    
    this.listening = false;
    this._stopWaveformVisualization();
    this._stopTypingAnimation();
    
    try {
      this.recognition.stop();
    } catch (e) {
      // Ignore stop errors
    }
    
    this._emitStateChange("idle");
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
   * @param {boolean} [options.skipLipSync] - Skip lip-sync events
   */
  async speak(text, options = {}) {
    if (!text || (!this.speakReplies && !options.force)) return;

    const cleanText = text.trim();
    if (!cleanText) return;

    this.speaking = true;
    this._emitStateChange("speaking");

    try {
      const token = await this.getToken();
      if (!token) throw new Error("No auth token");

      // Auto-select voice based on text language
      let voice = options.voice || this.selectedVoice;
      const isTelugu = this._isTeluguText(cleanText);
      
      if (isTelugu && !voice.startsWith("te-")) {
        voice = "te-IN-ShrutiNeural";
      } else if (!isTelugu && voice.startsWith("te-")) {
        voice = "en-IN-NeerjaNeural";
      }

      // Persist voice selection
      this.selectedVoice = voice;
      localStorage.setItem(this.STORAGE_KEYS.voice, voice);

      const lang = voice.startsWith("te-") ? "te" : "en";

      const res = await fetch(this.basePath + "/api/voice/speak", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-FRIDAY-Control-Token": token
        },
        body: JSON.stringify({
          text: cleanText,
          voice,
          lang
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
        this.speaking = false;
        this._emitStateChange("idle");
        if (!options.skipLipSync) this._triggerLipSync(0);
      };
      this.currentAudio.onerror = () => {
        URL.revokeObjectURL(url);
        this.speaking = false;
        this._emitStateChange("idle");
        if (!options.skipLipSync) this._triggerLipSync(0);
      };

      // Setup audio analysis for lip-sync
      if (!options.skipLipSync && this.lipSyncEnabled) {
        await this._setupLipSyncAudio(this.currentAudio);
      }

      await this.currentAudio.play();
    } catch (e) {
      this.speaking = false;
      this._emitStateChange("idle");
      this.onError("Speech output failed: " + e.message);
      if (!options.skipLipSync) this._triggerLipSync(0);
    }
  }

  /**
   * Process voice command - the single mode: User speaks → Friday processes → Friday executes → Friday speaks reply
   * @param {string} text - Voice command text
   */
  async processCommand(text) {
    if (this.processing) return;
    
    this.processing = true;
    this.stopListening();
    this._emitStateChange("processing");

    try {
      const token = await this.getToken();
      if (!token) throw new Error("No auth token");

      // Submit as autonomous goal for execution
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

      // Speak acknowledgment
      await this.speak("Working on it.", { force: true });

      // Poll for completion and speak result
      await this._pollGoalAndSpeak(goalId, token);

    } catch (e) {
      this.onError("Voice command failed: " + e.message);
      await this.speak("Sorry, that didn't work. " + e.message, { force: true });
    } finally {
      this.processing = false;
      this._emitStateChange("idle");
    }
  }

  /**
   * Register callback for final results
   * @param {Function} callback - Callback function(text)
   */
  onResult(callback) {
    this.onResultCallback = callback || (() => {});
  }

  /**
   * Register callback for errors
   * @param {Function} callback - Callback function(error)
   */
  onError(callback) {
    this.onError = callback || ((msg) => console.error("[FridayVoice]", msg));
  }

  /**
   * Register callback for interim results
   * @param {Function} callback - Callback function(text)
   */
  onInterim(callback) {
    this.onInterimCallback = callback || (() => {});
  }

  /**
   * Register callback for state changes
   * @param {Function} callback - Callback function(state)
   */
  onStateChange(callback) {
    this.onStateChangeCallback = callback || (() => {});
  }

  /**
   * Set speak replies setting
   * @param {boolean} enabled 
   */
  setSpeakReplies(enabled) {
    this.speakReplies = enabled;
    localStorage.setItem(this.STORAGE_KEYS.speakReplies, String(enabled));
  }

  /**
   * Set STT language
   * @param {string} lang - Language code (en-IN, te-IN)
   */
  setSttLanguage(lang) {
    this.sttLang = lang;
    localStorage.setItem(this.STORAGE_KEYS.sttLang, lang);
    if (this.recognition) {
      this.recognition.lang = lang;
    }
  }

  /**
   * Enable/disable auto language detection
   * @param {boolean} enabled 
   */
  setAutoLanguageDetect(enabled) {
    this.autoLanguageDetect = enabled;
    localStorage.setItem(this.STORAGE_KEYS.autoLanguageDetect, String(enabled));
  }

  /**
   * Set voice
   * @param {string} voice - Voice ID
   */
  setVoice(voice) {
    if (this.VOICES[voice]) {
      this.selectedVoice = voice;
      localStorage.setItem(this.STORAGE_KEYS.voice, voice);
    }
  }

  /**
   * Get current state
   * @returns {string} - Current state: idle, listening, processing, speaking
   */
  getState() {
    if (this.listening) return "listening";
    if (this.processing) return "processing";
    if (this.speaking) return "speaking";
    return "idle";
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
    return this.speaking;
  }

  /**
   * Check if currently processing
   */
  isProcessing() {
    return this.processing;
  }

  /**
   * Get available voices
   * @returns {Object} - Voice catalog
   */
  getVoices() {
    return this.VOICES;
  }

  /**
   * Clean up resources
   */
  destroy() {
    this.stopListening();
    this._stopWaveformVisualization();
    this._stopTypingAnimation();
    this._disconnectWebSocket();
    
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
    
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }
    
    this._emitStateChange("destroyed");
  }

  // ==================== Private Methods ====================

  _loadPreferences() {
    // Voice
    this.selectedVoice = localStorage.getItem(this.STORAGE_KEYS.voice) || "en-IN-NeerjaNeural";
    
    // STT Language
    this.sttLang = localStorage.getItem(this.STORAGE_KEYS.sttLang) || "en-IN";
    
    // Speak Replies
    const savedSpeakReplies = localStorage.getItem(this.STORAGE_KEYS.speakReplies);
    this.speakReplies = savedSpeakReplies !== "false"; // default true
    
    // Auto Language Detect
    const savedAutoDetect = localStorage.getItem(this.STORAGE_KEYS.autoLanguageDetect);
    this.autoLanguageDetect = savedAutoDetect !== "false"; // default true
  }

  _setupSpeechRecognition() {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {
      this.onError("Speech recognition not supported in this browser");
      return;
    }

    this.recognition = new SpeechRec();
    this.recognition.continuous = true;
    this.recognition.interimResults = true;
    this.recognition.lang = this.sttLang;

    this.recognition.onresult = this._onResult;
    this.recognition.onend = this._onEnd;
    this.recognition.onerror = this._onError;
  }

  _setupAudioContext() {
    try {
      this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 512;
      this.analyser.smoothingTimeConstant = 0.8;
      this.waveformData = new Uint8Array(this.analyser.frequencyBinCount);
    } catch (e) {
      console.warn("AudioContext not available:", e);
    }
  }

  _setupWaveformCanvas() {
    if (!this.waveformCanvas) return;
    
    const ctx = this.waveformCanvas.getContext("2d");
    this.waveformCanvas.width = this.waveformCanvas.clientWidth * (window.devicePixelRatio || 1);
    this.waveformCanvas.height = this.waveformCanvas.clientHeight * (window.devicePixelRatio || 1);
    ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);
  }

  async _connectWebSocket() {
    if (!this.wsUrl) return;
    
    try {
      this.ws = new WebSocket(this.wsUrl);
      
      this.ws.onopen = () => {
        console.log("[FridayVoice] WebSocket connected");
        this.wsReconnectAttempts = 0;
        // Subscribe to voice topic
        this.ws.send(JSON.stringify({ type: "subscribe", topics: ["voice", "agents"] }));
      };
      
      this.ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          this._handleWebSocketMessage(msg);
        } catch (e) {
          console.warn("[FridayVoice] WS message parse error:", e);
        }
      };
      
      this.ws.onclose = () => {
        console.log("[FridayVoice] WebSocket disconnected");
        this._scheduleReconnect();
      };
      
      this.ws.onerror = (error) => {
        console.error("[FridayVoice] WebSocket error:", error);
      };
    } catch (e) {
      console.warn("[FridayVoice] WebSocket connection failed:", e);
      this._scheduleReconnect();
    }
  }

  _scheduleReconnect() {
    if (this.wsReconnectAttempts >= this.maxWsReconnectAttempts) {
      console.log("[FridayVoice] Max reconnect attempts reached");
      return;
    }
    
    this.wsReconnectAttempts++;
    const delay = this.wsReconnectDelay * Math.pow(2, this.wsReconnectAttempts - 1);
    setTimeout(() => this._connectWebSocket(), delay);
  }

  _disconnectWebSocket() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  _handleWebSocketMessage(msg) {
    if (msg.topic === "voice") {
      if (msg.type === "audio_level" && this.listening) {
        this._updateWaveformFromWS(msg.data.level);
      } else if (msg.type === "transcript") {
        this.onInterimCallback(msg.data.text);
      } else if (msg.type === "result") {
        this.onResultCallback(msg.data.text);
      }
    } else if (msg.topic === "agents") {
      // Real-time agent updates
      this._emitStateChange("agent_update", msg.data);
    }
  }

  _onResult(event) {
    let interim = "";
    let finalText = "";
    
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i];
      if (result.isFinal) {
        finalText = result[0].transcript.trim();
      } else {
        interim += result[0].transcript;
      }
    }

    // Update interim text for typing animation
    this.currentInterimText = interim;
    
    if (interim) {
      this.onInterimCallback(interim);
    }

    if (finalText) {
      this.onResultCallback(finalText);
      this._handleVoiceCommand(finalText);
    }
  }

  _onEnd() {
    if (this.listening) {
      try {
        this.recognition.start();
      } catch (e) {
        this.listening = false;
        this._stopWaveformVisualization();
        this._stopTypingAnimation();
        this._emitStateChange("idle");
      }
    } else {
      this._stopWaveformVisualization();
      this._stopTypingAnimation();
      this._emitStateChange("idle");
    }
  }

  _onError(event) {
    this.listening = false;
    this._stopWaveformVisualization();
    this._stopTypingAnimation();
    this._emitStateChange("idle");

    switch (event.error) {
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
        this.onError("Speech recognition error: " + event.error);
    }
  }

  async _handleVoiceCommand(text) {
    const cleanText = text.trim();
    if (!cleanText) return;

    // Auto-detect language and update STT if enabled
    if (this.autoLanguageDetect) {
      const isTelugu = this._isTeluguText(cleanText);
      const newLang = isTelugu ? "te-IN" : "en-IN";
      if (newLang !== this.sttLang) {
        this.setSttLanguage(newLang);
      }
    }

    // Process the command
    await this.processCommand(cleanText);
  }

  async _pollGoalAndSpeak(goalId, token) {
    const poll = async () => {
      try {
        const res = await fetch(this.basePath + "/api/autonomous/goals/" + goalId, {
          headers: { "X-FRIDAY-Control-Token": token }
        });

        if (!res.ok) throw new Error("Poll failed");

        const goal = await res.json();

        if (goal) {
          if (goal.status === "COMPLETED" || goal.status === "PARTIAL" || goal.status === "FAILED") {
            const summary = goal.summary || "Done.";
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

  // ==================== Waveform Visualization ====================

  _startWaveformVisualization() {
    if (!this.waveformCanvas || !this.audioContext) return;

    // Resume audio context if suspended
    if (this.audioContext.state === "suspended") {
      this.audioContext.resume();
    }

    // Get microphone access
    navigator.mediaDevices.getUserMedia({ audio: true })
      .then(stream => {
        this.microphone = this.audioContext.createMediaStreamSource(stream);
        this.microphone.connect(this.analyser);
        this._animateWaveform();
      })
      .catch(err => {
        console.warn("Microphone access denied for waveform:", err);
        // Fallback: generate simulated waveform
        this._animateSimulatedWaveform();
      });
  }

  _stopWaveformVisualization() {
    if (this.waveformAnimationId) {
      cancelAnimationFrame(this.waveformAnimationId);
      this.waveformAnimationId = null;
    }
    
    if (this.microphone) {
      this.microphone.disconnect();
      this.microphone = null;
    }
    
    // Clear canvas
    if (this.waveformCanvas) {
      const ctx = this.waveformCanvas.getContext("2d");
      ctx.clearRect(0, 0, this.waveformCanvas.width, this.waveformCanvas.height);
    }
  }

  _animateWaveform() {
    if (!this.listening) return;
    
    this.waveformAnimationId = requestAnimationFrame(() => this._animateWaveform());
    
    this.analyser.getByteFrequencyData(this.waveformData);
    this._drawWaveform(this.waveformData);
    
    // Send audio level to WebSocket
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      const avgLevel = this.waveformData.reduce((a, b) => a + b, 0) / this.waveformData.length / 255;
      this.ws.send(JSON.stringify({ 
        type: "audio_level", 
        topic: "voice", 
        data: { level: avgLevel } 
      }));
    }
    
    // Trigger lip-sync for character if listening
    if (this.character && this.lipSyncEnabled) {
      const avgLevel = this.waveformData.reduce((a, b) => a + b, 0) / this.waveformData.length / 255;
      this._triggerLipSync(avgLevel * 0.5); // Reduced for listening
    }
  }

  _animateSimulatedWaveform() {
    if (!this.listening) return;
    
    this.waveformAnimationId = requestAnimationFrame(() => this._animateSimulatedWaveform());
    
    // Generate simulated waveform data
    const simulatedData = new Uint8Array(this.analyser?.frequencyBinCount || 256);
    const time = Date.now() / 1000;
    
    for (let i = 0; i < simulatedData.length; i++) {
      const freq = i / simulatedData.length;
      const amplitude = Math.sin(time * 10 + freq * 20) * 0.5 + 0.5;
      simulatedData[i] = Math.floor(amplitude * 128 + Math.random() * 64);
    }
    
    this._drawWaveform(simulatedData);
  }

  _drawWaveform(data) {
    if (!this.waveformCanvas) return;
    
    const ctx = this.waveformCanvas.getContext("2d");
    const width = this.waveformCanvas.clientWidth;
    const height = this.waveformCanvas.clientHeight;
    
    ctx.clearRect(0, 0, width, height);
    
    const centerY = height / 2;
    const barWidth = width / data.length * 2;
    const maxHeight = height * 0.4;
    
    // Draw gradient
    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, "#00ffcc");
    gradient.addColorStop(0.5, "#7ee0b5");
    gradient.addColorStop(1, "#00ffcc");
    
    ctx.fillStyle = gradient;
    
    for (let i = 0; i < data.length; i += 2) {
      const value = data[i] / 255;
      const barHeight = value * maxHeight;
      const x = i * barWidth;
      const y = centerY - barHeight / 2;
      
      ctx.fillRect(x, y, barWidth, barHeight);
    }
    
    // Mirror for symmetric look
    ctx.save();
    ctx.scale(1, -1);
    ctx.translate(0, -height);
    ctx.fillStyle = gradient;
    
    for (let i = 0; i < data.length; i += 2) {
      const value = data[i] / 255;
      const barHeight = value * maxHeight;
      const x = i * barWidth;
      const y = centerY - barHeight / 2;
      
      ctx.fillRect(x, y, barWidth, barHeight);
    }
    
    ctx.restore();
  }

  _updateWaveformFromWS(level) {
    if (!this.waveformCanvas) return;
    
    const ctx = this.waveformCanvas.getContext("2d");
    const width = this.waveformCanvas.clientWidth;
    const height = this.waveformCanvas.clientHeight;
    
    // Add to history
    this.waveformHistory.push(level);
    if (this.waveformHistory.length > width) {
      this.waveformHistory.shift();
    }
    
    ctx.clearRect(0, 0, width, height);
    
    const centerY = height / 2;
    const maxHeight = height * 0.4;
    
    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, "#b7a7ff");
    gradient.addColorStop(0.5, "#7ee0b5");
    gradient.addColorStop(1, "#b7a7ff");
    
    ctx.fillStyle = gradient;
    
    for (let i = 0; i < this.waveformHistory.length; i++) {
      const value = this.waveformHistory[i];
      const barHeight = value * maxHeight;
      const x = i;
      const y = centerY - barHeight / 2;
      
      ctx.fillRect(x, y, 2, barHeight);
    }
  }

  // ==================== Typing Animation ====================

  _startTypingAnimation() {
    this.displayedInterimText = "";
    this._animateTyping();
  }

  _stopTypingAnimation() {
    if (this.typingAnimationId) {
      clearInterval(this.typingAnimationId);
      this.typingAnimationId = null;
    }
    this.displayedInterimText = "";
  }

  _animateTyping() {
    this.typingAnimationId = setInterval(() => {
      if (!this.listening) {
        this._stopTypingAnimation();
        return;
      }
      
      if (this.displayedInterimText.length < this.currentInterimText.length) {
        this.displayedInterimText = this.currentInterimText.slice(0, this.displayedInterimText.length + 1);
        this.onInterimCallback(this.displayedInterimText + "|"); // Add cursor
      } else if (this.displayedInterimText.length > this.currentInterimText.length) {
        this.displayedInterimText = this.currentInterimText;
        this.onInterimCallback(this.displayedInterimText);
      }
    }, 50);
  }

  // ==================== Lip-Sync ====================

  async _setupLipSyncAudio(audioElement) {
    if (!this.audioContext || !this.lipSyncEnabled) return;
    
    try {
      // Create a new audio context for analysis if needed
      const source = this.audioContext.createMediaElementSource(audioElement);
      const analyser = this.audioContext.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.3;
      
      source.connect(analyser);
      analyser.connect(this.audioContext.destination);
      
      const lipSyncData = new Uint8Array(analyser.frequencyBinCount);
      
      const animateLipSync = () => {
        if (audioElement.paused || audioElement.ended) {
          this._triggerLipSync(0);
          return;
        }
        
        analyser.getByteFrequencyData(lipSyncData);
        
        // Calculate average amplitude in speech frequency range (300Hz - 3400Hz)
        // With fftSize=256 and sampleRate=44100, each bin = 172Hz
        // Speech range: bins 2-20 approximately
        let sum = 0;
        for (let i = 2; i < 20; i++) {
          sum += lipSyncData[i];
        }
        const avg = sum / 18 / 255;
        
        this._triggerLipSync(avg);
        requestAnimationFrame(animateLipSync);
      };
      
      animateLipSync();
    } catch (e) {
      console.warn("Lip-sync setup failed:", e);
    }
  }

  _triggerLipSync(amplitude) {
    const now = Date.now();
    if (now - this.lastLipSyncTime < 50) return; // Throttle to 20fps
    this.lastLipSyncTime = now;
    
    // Emit to character if available
    if (this.character && typeof this.character.speak === "function") {
      this.character.speak(amplitude);
    }
    
    // Emit to WebSocket for remote clients
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        type: "lip_sync",
        topic: "voice",
        data: { amplitude }
      }));
    }
    
    // Callback for external lip-sync handlers
    this._emitStateChange("lip_sync", { amplitude });
  }

  _isTeluguText(text) {
    // Telugu Unicode range: U+0C00 to U+0C7F
    return /[\u0C00-\u0C7F]/.test(text);
  }

  _emitStateChange(state, data = {}) {
    this.onStateChangeCallback({ state, data, timestamp: Date.now() });
  }

  // ==================== Audio Processing for Real-time ====================

  _onAudioProcess(event) {
    // Real-time audio processing callback
    // Can be used for custom audio analysis
  }
}

// Export for module systems
if (typeof module !== "undefined" && module.exports) {
  module.exports = FridayVoice;
}

// Export for global usage
if (typeof window !== "undefined") {
  window.FridayVoice = FridayVoice;
}