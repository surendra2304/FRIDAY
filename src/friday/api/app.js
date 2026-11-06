/**
 * FRIDAY — voice-first companion interface
 *
 * One interaction model: the owner speaks or types, FRIDAY decomposes the
 * request, drives the specialist agents, and answers out loud. Live agent work
 * is mirrored into the fleet panel and the flow view.
 */

const BASE = (() => {
  const p = window.location.pathname;
  return p === "/friday" || p.startsWith("/friday/") ? "/friday" : "";
})();
const V = "20261106c";

/* ------------------------------------------------------------------ */
/* Tiny DOM helpers                                                    */
/* ------------------------------------------------------------------ */

const ui = {};
const UI_KEYS = [
  "statusText", "statusDot", "micBtn", "textInput", "sendBtn", "transcript",
  "settingsBtn", "settingsClose", "settingsPanel", "sttLang", "ttsVoice",
  "speakReplies", "autoLangDetect", "themeMode", "reducedMotion", "agentToggles",
  "resetDefaults", "fleetToggle", "flowToggle", "clock", "hintLine",
  "orbCanvas", "waveform", "orbCaption"
];

function cacheUI() {
  for (const key of UI_KEYS) ui[key] = document.getElementById(key);
}

function el(key) {
  if (!ui[key]) ui[key] = document.getElementById(key);
  return ui[key];
}

const AGENTS = [
  "friday", "inference", "memora", "stratex", "futuris",
  "intelx", "forge", "sentinel", "cortex", "vyralx"
];

/* ------------------------------------------------------------------ */
/* Settings                                                            */
/* ------------------------------------------------------------------ */

const DEFAULT_SETTINGS = {
  sttLang: "en-IN",
  ttsVoice: "en-IN-NeerjaNeural",
  speakReplies: true,
  autoLangDetect: true,
  themeMode: "dark",
  accent: "mint",
  reducedMotion: false
};

const settings = { ...DEFAULT_SETTINGS };

function loadSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem("friday_settings") || "{}");
    Object.assign(settings, DEFAULT_SETTINGS, saved);
  } catch { /* ignore corrupt storage */ }
}

function saveSettings() {
  try {
    localStorage.setItem("friday_settings", JSON.stringify(settings));
  } catch { /* storage may be unavailable */ }
}

function applyAppearance() {
  const root = document.documentElement;
  root.dataset.accent = settings.accent;
  root.dataset.theme = settings.themeMode;
  root.classList.toggle("reduce-motion", !!settings.reducedMotion);
}

/* ------------------------------------------------------------------ */
/* Status + toasts                                                     */
/* ------------------------------------------------------------------ */

function setStatus(text, state = "info") {
  const txt = el("statusText");
  const dot = el("statusDot");
  if (txt) txt.textContent = text;
  if (dot) dot.className = "status-dot " + state;
}

function toast(message, type = "info") {
  const node = document.createElement("div");
  node.className = "toast toast-" + type;
  node.textContent = message;
  document.body.appendChild(node);
  requestAnimationFrame(() => node.classList.add("show"));
  setTimeout(() => {
    node.classList.remove("show");
    setTimeout(() => node.remove(), 320);
  }, 3600);
}

/* ------------------------------------------------------------------ */
/* Auth                                                                */
/* ------------------------------------------------------------------ */

let controlToken = null;
let tokenExpiry = 0;

async function getToken(force = false) {
  if (!force && controlToken && Date.now() / 1000 < tokenExpiry - 30) {
    return controlToken;
  }
  const res = await fetch(BASE + "/api/control/session", { cache: "no-store" });
  if (!res.ok) throw new Error("control session " + res.status);
  const data = await res.json();
  controlToken = data.token;
  tokenExpiry = data.expires_at || Date.now() / 1000 + 900;
  return controlToken;
}

async function apiFetch(path, options = {}) {
  const token = await getToken();
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (token) headers["X-FRIDAY-Control-Token"] = token;
  const res = await fetch(BASE + path, { ...options, headers });
  if (res.status === 401 || res.status === 403) {
    const fresh = await getToken(true);
    if (fresh) {
      const retry = await fetch(BASE + path, {
        ...options,
        headers: { ...headers, "X-FRIDAY-Control-Token": fresh }
      });
      return retry;
    }
  }
  return res;
}

/* ------------------------------------------------------------------ */
/* Orb                                                                 */
/* ------------------------------------------------------------------ */

const PALETTE = {
  idle:      { a: [16, 185, 129],  b: [6, 182, 212] },
  listening: { a: [6, 182, 212],   b: [56, 189, 248] },
  thinking:  { a: [168, 85, 247],  b: [245, 158, 11] },
  speaking:  { a: [52, 224, 161],  b: [6, 182, 212] }
};

const Orb = {
  canvas: null,
  ctx: null,
  dpr: 1,
  w: 0,
  h: 0,
  state: "idle",
  time: 0,
  amp: 0,
  targetAmp: 0,
  particles: [],
  reduced: false,
  running: false,
  last: 0,

  init(canvas) {
    this.canvas = canvas;
    if (!canvas) return;
    this.ctx = canvas.getContext("2d");
    this.reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.resize();
    window.addEventListener("resize", () => this.resize(), { passive: true });

    for (let i = 0; i < 74; i++) {
      this.particles.push({
        angle: Math.random() * Math.PI * 2,
        radius: 1.12 + Math.random() * 0.95,
        speed: (0.12 + Math.random() * 0.4) * (Math.random() < 0.5 ? -1 : 1),
        size: 0.6 + Math.random() * 1.9,
        phase: Math.random() * Math.PI * 2,
        drift: 0.55 + Math.random() * 0.9
      });
    }

    if (!this.reduced) {
      this.running = true;
      requestAnimationFrame((t) => this.loop(t));
    } else {
      this.draw(0);
    }
  },

  resize() {
    if (!this.canvas) return;
    const rect = this.canvas.getBoundingClientRect();
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.w = Math.max(1, rect.width);
    this.h = Math.max(1, rect.height);
    this.canvas.width = Math.floor(this.w * this.dpr);
    this.canvas.height = Math.floor(this.h * this.dpr);
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    if (this.reduced) this.draw(0);
  },

  setState(state) {
    if (this.state === state) return;
    this.state = state;
    if (state === "listening") this.targetAmp = 0.55;
    if (state === "speaking") this.targetAmp = 0.75;
    if (state === "thinking") this.targetAmp = 0.3;
    if (state === "idle") this.targetAmp = 0;
    if (this.reduced) this.draw(0);
  },

  setAmplitude(value) {
    this.targetAmp = Math.max(0, Math.min(1, value));
  },

  loop(now) {
    if (!this.running) return;
    const dt = Math.min(64, now - (this.last || now));
    this.last = now;
    this.time += dt / 1000;
    this.amp += (this.targetAmp - this.amp) * Math.min(1, dt / 140);
    if (this.state === "idle") this.amp += (Math.sin(this.time * 1.4) * 0.04 + 0.04 - this.amp) * 0.02;
    this.draw(this.time);
    requestAnimationFrame((t) => this.loop(t));
  },

  draw(t) {
    const ctx = this.ctx;
    if (!ctx) return;
    const { w, h } = this;
    const cx = w / 2;
    const cy = h * 0.46;
    const R = Math.min(w, h) * 0.155;
    const pal = PALETTE[this.state] || PALETTE.idle;
    const [ar, ag, ab] = pal.a;
    const [br, bg, bb] = pal.b;
    const amp = this.amp;

    ctx.clearRect(0, 0, w, h);

    /* ---- atmosphere ---- */
    const halo = ctx.createRadialGradient(cx, cy, R * 0.2, cx, cy, R * 4.2);
    halo.addColorStop(0, `rgba(${ar},${ag},${ab},${0.16 + amp * 0.16})`);
    halo.addColorStop(0.45, `rgba(${br},${bg},${bb},${0.07 + amp * 0.06})`);
    halo.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = halo;
    ctx.fillRect(0, 0, w, h);

    /* ---- orbiting particles ---- */
    for (const p of this.particles) {
      const angle = p.angle + t * p.speed + amp * 0.6;
      const wobble = 1 + Math.sin(t * p.drift + p.phase) * 0.05;
      const radius = R * p.radius * wobble;
      const x = cx + Math.cos(angle) * radius;
      const y = cy + Math.sin(angle) * radius * 0.62;
      const depth = (Math.sin(angle) + 1) / 2;
      const alpha = 0.12 + depth * (0.35 + amp * 0.4);
      ctx.beginPath();
      ctx.arc(x, y, p.size * (0.7 + depth * 0.6), 0, Math.PI * 2);
      ctx.fillStyle = depth > 0.55
        ? `rgba(${br},${bg},${bb},${alpha})`
        : `rgba(${ar},${ag},${ab},${alpha})`;
      ctx.fill();
    }

    /* ---- aura rings ---- */
    for (let i = 0; i < 3; i++) {
      const rr = R * (1.35 + i * 0.22) + Math.sin(t * 0.8 + i) * R * 0.03;
      ctx.beginPath();
      ctx.ellipse(cx, cy, rr, rr * 0.62, Math.sin(t * 0.16 + i * 2.1) * 0.5, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(${ar},${ag},${ab},${0.16 - i * 0.035 + amp * 0.1})`;
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    /* ---- speaking ripples ---- */
    if (this.state === "speaking") {
      for (let i = 0; i < 3; i++) {
        const phase = ((t * 0.55 + i * 0.33) % 1);
        const rr = R * (1.05 + phase * 1.5);
        ctx.beginPath();
        ctx.arc(cx, cy, rr, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(${br},${bg},${bb},${(1 - phase) * 0.32 * (0.4 + amp)})`;
        ctx.lineWidth = 1.6;
        ctx.stroke();
      }
    }

    /* ---- thought arcs ---- */
    if (this.state === "thinking") {
      for (let i = 0; i < 3; i++) {
        const start = t * (0.9 + i * 0.35) + i * 1.7;
        const rr = R * (1.18 + i * 0.16);
        ctx.beginPath();
        ctx.arc(cx, cy, rr, start, start + 1.15);
        ctx.strokeStyle = `rgba(${ar},${ag},${ab},${0.5 - i * 0.12})`;
        ctx.lineWidth = 2.2 - i * 0.4;
        ctx.lineCap = "round";
        ctx.stroke();
      }
    }

    /* ---- core ---- */
    const breathe = 1 + Math.sin(t * 1.15) * 0.022 + amp * 0.14;
    const coreR = R * breathe;
    const core = ctx.createRadialGradient(
      cx - coreR * 0.32, cy - coreR * 0.4, coreR * 0.08,
      cx, cy, coreR
    );
    core.addColorStop(0, `rgba(255,255,255,${0.74 - amp * 0.1})`);
    core.addColorStop(0.2, `rgba(${Math.min(255, ar + 90)},${Math.min(255, ag + 70)},${Math.min(255, ab + 70)},0.9)`);
    core.addColorStop(0.62, `rgba(${ar},${ag},${ab},0.9)`);
    core.addColorStop(1, `rgba(${Math.floor(ar * 0.28)},${Math.floor(ag * 0.3)},${Math.floor(ab * 0.4)},0.92)`);

    ctx.save();
    ctx.shadowBlur = 60 + amp * 60;
    ctx.shadowColor = `rgba(${ar},${ag},${ab},0.65)`;
    ctx.beginPath();
    ctx.arc(cx, cy, coreR, 0, Math.PI * 2);
    ctx.fillStyle = core;
    ctx.fill();
    ctx.restore();

    ctx.beginPath();
    ctx.arc(cx, cy, coreR, 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(255,255,255,${0.22 + amp * 0.2})`;
    ctx.lineWidth = 1;
    ctx.stroke();

    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, coreR, 0, Math.PI * 2);
    ctx.clip();

    /* volume: light falls top-left, shadow gathers bottom-right */
    const shade = ctx.createRadialGradient(
      cx + coreR * 0.42, cy + coreR * 0.46, coreR * 0.05,
      cx, cy, coreR * 1.05
    );
    shade.addColorStop(0, "rgba(0,0,0,0.34)");
    shade.addColorStop(0.6, "rgba(0,0,0,0.06)");
    shade.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = shade;
    ctx.fillRect(cx - coreR, cy - coreR, coreR * 2, coreR * 2);

    /* specular */
    const sheen = ctx.createRadialGradient(
      cx - coreR * 0.34, cy - coreR * 0.4, 0,
      cx - coreR * 0.34, cy - coreR * 0.4, coreR * 0.5
    );
    sheen.addColorStop(0, "rgba(255,255,255,0.5)");
    sheen.addColorStop(0.55, "rgba(255,255,255,0.12)");
    sheen.addColorStop(1, "rgba(255,255,255,0)");
    ctx.beginPath();
    ctx.ellipse(cx - coreR * 0.34, cy - coreR * 0.4, coreR * 0.5, coreR * 0.42, -0.5, 0, Math.PI * 2);
    ctx.fillStyle = sheen;
    ctx.fill();

    /* thin rim light along the lower edge */
    ctx.beginPath();
    ctx.arc(cx, cy, coreR * 0.985, Math.PI * 0.1, Math.PI * 1.02);
    ctx.strokeStyle = `rgba(${br},${bg},${bb},${0.45 + amp * 0.3})`;
    ctx.lineWidth = 1.6;
    ctx.stroke();

    ctx.restore();

    /* ---- listening halo bars ---- */
    if (this.state === "listening") {
      const bars = 44;
      for (let i = 0; i < bars; i++) {
        const a = (i / bars) * Math.PI * 2 + t * 0.25;
        const level = 0.35 + Math.abs(Math.sin(i * 1.7 + t * 3.1)) * (0.3 + amp);
        const r0 = R * 1.28;
        const r1 = r0 + R * 0.2 * level;
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(a) * r0, cy + Math.sin(a) * r0 * 0.82);
        ctx.lineTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1 * 0.82);
        ctx.strokeStyle = `rgba(${br},${bg},${bb},${0.22 + level * 0.4})`;
        ctx.lineWidth = 2;
        ctx.lineCap = "round";
        ctx.stroke();
      }
    }
  }
};

/* ------------------------------------------------------------------ */
/* Transcript                                                          */
/* ------------------------------------------------------------------ */

let typingNode = null;

function transcriptBox() {
  return el("transcript");
}

function scrollTranscript() {
  const box = transcriptBox();
  if (box) box.scrollTop = box.scrollHeight;
}

function appendMessage(role, text, agents = []) {
  const box = transcriptBox();
  if (!box) return null;
  const wrap = document.createElement("div");
  wrap.className = "msg " + (role === "user" ? "msg-user" : "msg-friday");

  const label = document.createElement("span");
  label.className = "msg-label";
  label.textContent = role === "user" ? "You" : "FRIDAY";

  const body = document.createElement("div");
  body.className = "msg-body";
  body.textContent = text;

  wrap.append(label, body);

  if (agents.length) {
    const chips = document.createElement("div");
    chips.className = "msg-agents";
    for (const name of agents) {
      const chip = document.createElement("span");
      chip.className = "agent-chip";
      chip.textContent = name;
      chips.appendChild(chip);
    }
    wrap.appendChild(chips);
  }

  box.appendChild(wrap);
  scrollTranscript();
  return wrap;
}

function showTyping() {
  const box = transcriptBox();
  if (!box) return;
  clearTyping();
  const node = document.createElement("div");
  node.className = "msg msg-friday msg-typing";
  const body = document.createElement("div");
  body.className = "msg-body";
  for (let i = 0; i < 3; i++) {
    const dot = document.createElement("span");
    dot.className = "typing-dot";
    body.appendChild(dot);
  }
  node.appendChild(body);
  box.appendChild(node);
  typingNode = node;
  scrollTranscript();
}

function clearTyping() {
  if (typingNode && typingNode.parentNode) typingNode.remove();
  typingNode = null;
}

function setCaption(text) {
  const cap = el("orbCaption");
  if (cap) {
    cap.textContent = text || "";
    cap.classList.toggle("visible", Boolean(text));
  }
}

/* ------------------------------------------------------------------ */
/* Speech synthesis                                                    */
/* ------------------------------------------------------------------ */

let audioCtx = null;
let analyser = null;
let micAnalyser = null;
let micStream = null;
let amplitudeData = null;
let usingRealAnalysis = false;
let currentAudio = null;

function detectLang(text) {
  return /[\u0C00-\u0C7F]/.test(text) ? "te" : "en";
}

const VOICE_FOR_LANG = { en: "en-IN-NeerjaNeural", te: "te-IN-ShrutiNeural" };

async function speak(text) {
  const clean = String(text || "").trim();
  if (!clean || !settings.speakReplies) return;

  const lang = detectLang(clean);
  const voice = settings.ttsVoice && settings.ttsVoice !== "auto"
    ? settings.ttsVoice
    : VOICE_FOR_LANG[lang];

  Orb.setState("speaking");

  try {
    const res = await apiFetch("/api/voice/speak", {
      method: "POST",
      body: JSON.stringify({ text: clean, lang, voice })
    });
    if (!res.ok) throw new Error("tts " + res.status);
    const blob = await res.blob();
    if (!blob.size) throw new Error("empty audio");
    await playAudio(blob);
  } catch (err) {
    console.warn("[FRIDAY] neural voice unavailable:", err.message);
    await browserSpeak(clean, lang);
  } finally {
    Orb.setState("idle");
    Orb.setAmplitude(0);
  }
}

function playAudio(blob) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    currentAudio = audio;

    const finish = () => {
      URL.revokeObjectURL(url);
      currentAudio = null;
      usingRealAnalysis = false;
      resolve();
    };

    audio.onended = finish;
    audio.onerror = finish;

    try {
      if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === "suspended") audioCtx.resume();
      const source = audioCtx.createMediaElementSource(audio);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      analyser.connect(audioCtx.destination);
      amplitudeData = new Uint8Array(analyser.frequencyBinCount);
      usingRealAnalysis = true;
    } catch {
      usingRealAnalysis = false;
    }

    audio.play().catch((err) => {
      console.warn("[FRIDAY] playback blocked:", err.message);
      finish();
    });
  });
}

function browserSpeak(text, lang) {
  return new Promise((resolve) => {
    if (!("speechSynthesis" in window)) return resolve();
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = lang === "te" ? "te-IN" : "en-IN";
    utter.rate = 1;
    utter.pitch = 1.02;
    utter.onend = resolve;
    utter.onerror = resolve;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utter);
    setTimeout(resolve, Math.min(45000, text.length * 90));
  });
}

/* amplitude for the orb, updated from the animation loop */
function currentAmplitude() {
  if (usingRealAnalysis && analyser) {
    analyser.getByteTimeDomainData(amplitudeData);
    let peak = 0;
    for (let i = 0; i < amplitudeData.length; i += 4) {
      peak = Math.max(peak, Math.abs(amplitudeData[i] - 128) / 128);
    }
    return Math.min(1, peak * 2.4);
  }
  if (Orb.state === "speaking") {
    return 0.35 + Math.abs(Math.sin(performance.now() / 130)) * 0.4;
  }
  return 0;
}

/* ------------------------------------------------------------------ */
/* Speech recognition                                                  */
/* ------------------------------------------------------------------ */

let recognition = null;
let listening = false;
let interimText = "";

function buildRecognition() {
  const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Ctor) return null;

  const rec = new Ctor();
  rec.continuous = false;
  rec.interimResults = true;
  rec.maxAlternatives = 1;
  rec.lang = settings.sttLang || "en-IN";

  rec.onstart = () => {
    listening = true;
    interimText = "";
    el("micBtn")?.classList.add("listening");
    el("micBtn")?.setAttribute("aria-pressed", "true");
    Orb.setState("listening");
    setStatus("Listening", "listening");
    setCaption("Listening…");
    setHint("Speak now — I'm listening.");
  };

  rec.onresult = (event) => {
    let interim = "";
    let final = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i];
      if (result.isFinal) final += result[0].transcript;
      else interim += result[0].transcript;
    }
    interimText = interim;
    setHint(interim || "…");
    if (final.trim()) {
      setHint("");
      ask(final.trim(), "voice");
    }
  };

  rec.onerror = (event) => {
    if (event.error === "no-speech") {
      setHint("I didn't catch that. Try again?");
    } else if (event.error === "not-allowed" || event.error === "service-not-allowed") {
      toast("Microphone access is blocked. Allow it in your browser settings.", "error");
      setHint("Microphone blocked — you can type instead.");
    } else if (event.error !== "aborted") {
      setHint("Voice hiccup — type it instead?");
    }
  };

  rec.onend = () => {
    listening = false;
    el("micBtn")?.classList.remove("listening");
    el("micBtn")?.setAttribute("aria-pressed", "false");
    if (Orb.state === "listening") Orb.setState("idle");
    if (!isBusy) setStatus("Ready", "ready");
    setCaption("");
    if (!interimText) setHint("");
  };

  return rec;
}

function startListening() {
  if (listening) return;
  if (!recognition) recognition = buildRecognition();
  if (!recognition) {
    toast("This browser can't capture speech. Chrome or Edge works best.", "error");
    return;
  }
  recognition.lang = settings.sttLang || "en-IN";
  try {
    recognition.start();
  } catch (err) {
    console.warn("[FRIDAY] recognition start failed:", err.message);
  }
}

function stopListening() {
  if (recognition && listening) {
    try { recognition.stop(); } catch { /* already stopped */ }
  }
}

function toggleListening() {
  if (listening) stopListening();
  else startListening();
}

function setHint(text) {
  const hint = el("hintLine");
  if (!hint) return;
  if (text) {
    hint.textContent = text;
    hint.classList.add("active");
  } else {
    hint.textContent = "Tap the mic and talk — Telugu or English.";
    hint.classList.remove("active");
  }
}

/* ------------------------------------------------------------------ */
/* Fleet + flow                                                        */
/* ------------------------------------------------------------------ */

let fleet = null;
let flow = null;

async function initFleet() {
  const mod = await import(`/static/agent_fleet.js?v=${V}`);
  const FleetClass = mod.AgentFleet || window.AgentFleet;
  if (!FleetClass) throw new Error("AgentFleet export missing");

  fleet = new FleetClass({ basePath: "", autoConnect: false });
  await fleet.init(document.body);
  fleet.togglePanel(false);
  return fleet;
}

async function initFlow() {
  window.FRIDAY_COMPONENT_WS = false;
  await import(`/static/workflow_canvas.js?v=${V}`);
  flow = window.WorkflowCanvas;
  if (!flow || typeof flow.init !== "function") throw new Error("WorkflowCanvas missing");
  await flow.init(document.body, {
    onNodeClick: (agentId) => {
      if (fleet && fleet.expandAgent) fleet.expandAgent(agentId);
    }
  });
  return flow;
}

function normalizeAgent(raw) {
  const key = String(raw || "").trim().toLowerCase();
  if (!key) return null;
  if (AGENTS.includes(key)) return key;
  const alias = {
    "friday": "friday", "orchestrator": "friday",
    "inference": "inference", "gateway": "inference", "llm": "inference",
    "memora": "memora", "memory": "memora",
    "stratex": "stratex", "trading": "stratex",
    "futuris": "futuris", "forecast": "futuris", "forecasting": "futuris",
    "intelx": "intelx", "threat": "intelx", "osint": "intelx",
    "forge": "forge", "coding": "forge", "code": "forge",
    "sentinel": "sentinel", "security": "sentinel", "soc": "sentinel",
    "cortex": "cortex", "crm": "cortex",
    "vyralx": "vyralx", "video": "vyralx"
  };
  return alias[key] || key;
}

function markAgent(agentId, state, task) {
  const id = normalizeAgent(agentId);
  if (!id) return;
  const fleetStatus = state === "failed" ? "error"
    : state === "running" || state === "busy" ? "busy"
    : "online";
  if (fleet && fleet.updateAgent) {
    fleet.updateAgent(id, {
      status: fleetStatus,
      task: task || undefined,
      progress: state === "done" ? 1 : state === "running" ? 0.55 : undefined
    });
  }
  if (flow && flow.updateNodeState) {
    flow.updateNodeState(id, state);
  }
}

/**
 * Peer health snapshot, so the fleet reflects reality even before any work runs.
 * Never overwrites an agent that is mid-task.
 */
async function refreshFleetHealth() {
  if (!fleet) return;
  try {
    const res = await fetch(BASE + "/api/agents/status", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    window.__fridayHealth = { status: res.status, count: (data.agents || []).length, at: Date.now() };
    for (const agent of data.agents || []) {
      const id = normalizeAgent(agent.id || agent.name);
      if (!id) continue;
      const current = fleet.agentStates && fleet.agentStates.get(id);
      if (current && current.status === "busy") continue;
      const status = String(agent.status || "").toLowerCase();
      fleet.updateAgent(id, {
        status: status === "online" ? "online" : status === "degraded" ? "busy" : "offline",
        latency: agent.latency_ms
      });
    }
    const friday = fleet.agentStates && fleet.agentStates.get("friday");
    if (!friday || friday.status !== "busy") {
      fleet.updateAgent("friday", { status: "online" });
    }
  } catch (err) {
    window.__fridayHealth = { error: err.message, at: Date.now() };
    console.warn("[FRIDAY] fleet health unavailable:", err.message);
  }
}

function uniqueAgents(goal) {
  const names = [];
  for (const step of goal.steps || []) {
    const raw = step.agent || step.agent_name;
    if (!raw) continue;
    const name = String(raw).toLowerCase();
    if (!names.includes(name)) names.push(name);
  }
  return names;
}

const PROCESS_NOISE = /^(execution completed via|ok\b|success\b|completed\b|it confirmed|done\.?$)/i;

/**
 * Turn a finished goal into one honest, conversational line. The control plane
 * sometimes returns only process logs, and pretending that is an answer would
 * be worse than saying so.
 */
function composeReply(goal) {
  const raw = String(goal.summary || "").trim();
  const terminal = ["COMPLETED", "PARTIAL", "FAILED"].includes(String(goal.status || "").toUpperCase());
  const progressOnly = /^working on it/i.test(raw) || /steps finished so far/i.test(raw);

  if (raw && !(terminal && progressOnly)) return raw;

  const steps = goal.steps || [];
  const agents = uniqueAgents(goal).map((a) => a.charAt(0).toUpperCase() + a.slice(1));
  const results = steps
    .map((s) => String(s.result || "").trim())
    .filter((r) => r && !PROCESS_NOISE.test(r));

  if (String(goal.status).toUpperCase() === "FAILED") {
    return goal.error
      ? `That didn't come together — ${goal.error}`
      : "That didn't come together. Something on my side broke mid-run; ask me again and I'll retry.";
  }

  if (results.length) {
    const joined = results.slice(0, 2).join(" ");
    return joined.length > 520 ? joined.slice(0, 520).trimEnd() + "…" : joined;
  }

  if (agents.length) {
    const who = agents.length === 1 ? agents[0] : agents.slice(0, -1).join(", ") + " and " + agents[agents.length - 1];
    return `I ran that through ${who}, but all it handed back was process logging — no actual answer. Ask me again in a moment, or point me at a narrower question.`;
  }

  return "I couldn't get a usable result out of that one. Try rephrasing it as one concrete question.";
}

/* ------------------------------------------------------------------ */
/* Conversation                                                        */
/* ------------------------------------------------------------------ */

let isBusy = false;
let activeGoalId = null;
let activeGoalText = "";
let pollTimer = null;

async function ask(text, source = "text") {
  const goal = String(text || "").trim();
  if (!goal || isBusy) return;

  isBusy = true;
  activeGoalText = goal;
  if (source === "text") {
    const input = el("textInput");
    if (input) input.value = "";
  }
  setHint("");

  appendMessage("user", goal);
  showTyping();
  Orb.setState("thinking");
  setCaption("Thinking");
  setStatus("Thinking", "processing");
  markAgent("friday", "running", goal.slice(0, 120));
  if (flow && flow.open) flow.open();

  try {
    const res = await apiFetch("/api/autonomous/goals", {
      method: "POST",
      body: JSON.stringify({ goal, priority: 10 })
    });
    if (!res.ok) throw new Error("goal submit " + res.status);
    const data = await res.json();
    if (!data.goal_id) throw new Error("no goal id returned");
    activeGoalId = data.goal_id;
    pollGoal(data.goal_id, goal);
  } catch (err) {
    console.error("[FRIDAY] submit failed:", err);
    clearTyping();
    finishTurn("I couldn't reach my own control plane just now. Give me a few seconds and ask again.", "error");
  }
}

async function pollGoal(goalId, originalText) {
  let elapsed = 0;
  let terminalSince = 0;
  clearInterval(pollTimer);

  const tick = async () => {
    if (activeGoalId !== goalId) return;
    elapsed += 2500;
    try {
      const res = await apiFetch(`/api/autonomous/goals/${goalId}`);
      if (!res.ok) throw new Error("goal " + res.status);
      const goal = await res.json();
      window.__fridayLastGoal = goal;

      const steps = Array.isArray(goal.steps) ? goal.steps : [];
      const live = steps.filter((s) => (s.status || "").toUpperCase() === "RUNNING");
      const done = steps.filter((s) => (s.status || "").toUpperCase() === "COMPLETED");

      steps.forEach((step) => {
        const agentId = step.agent || step.agent_name || step.assigned_to;
        const status = String(step.status || "").toUpperCase();
        if (!agentId) return;
        if (status === "COMPLETED") markAgent(agentId, "done", step.description || step.task);
        else if (status === "RUNNING") markAgent(agentId, "running", step.description || step.task);
        else if (status === "FAILED") markAgent(agentId, "failed", step.description || step.task);
      });

      const terminal = ["COMPLETED", "PARTIAL", "FAILED"].includes(String(goal.status || "").toUpperCase());
      const rawSummary = String(goal.summary || "").trim();
      const summaryReady = Boolean(rawSummary)
        && !/^working on it/i.test(rawSummary)
        && !/steps finished so far/i.test(rawSummary);

      // The control plane can report a terminal status a moment before the
      // spoken answer exists. Hold the turn open rather than voicing a
      // progress line as if it were the answer.
      if (terminal && !summaryReady) {
        if (!terminalSince) terminalSince = Date.now();
        if (Date.now() - terminalSince < 20000) {
          setCaption("Finishing up");
          return;
        }
      }

      if (!terminal) {
        if (live.length) {
          const names = [...new Set(live.map((s) => (s.agent || s.agent_name || "").toLowerCase()))].filter(Boolean);
          const label = names.length ? names.join(" + ") : "the fleet";
          setCaption(`${label} working`);
          setHint(`${label} is on it…`);
        } else if (done.length && steps.length) {
          setCaption(`${done.length} of ${steps.length} done`);
        }
        if (elapsed > 150000) {
          clearInterval(pollTimer);
          pollTimer = null;
          finishTurn("This one is taking longer than I expected. It's still running in the background — open the flow view to watch it.", "info");
        }
        return;
      }

      clearInterval(pollTimer);
      pollTimer = null;

      const agentNames = [];
      steps.forEach((step) => {
        const raw = step.agent_name || step.agent;
        if (!raw) return;
        const name = String(raw);
        const display = name.charAt(0).toUpperCase() + name.slice(1).toLowerCase();
        if (!agentNames.includes(display)) agentNames.push(display);
      });

      steps.forEach((step) => {
        const agentId = step.agent || step.agent_name;
        const status = String(step.status || "").toUpperCase();
        if (agentId) markAgent(agentId, status === "FAILED" ? "failed" : "done", step.action || step.description);
      });
      markAgent("friday", String(goal.status).toUpperCase() === "FAILED" ? "failed" : "done");

      finishTurn(composeReply(goal), String(goal.status).toUpperCase() === "FAILED" ? "error" : "info", agentNames);
    } catch (err) {
      console.warn("[FRIDAY] poll error:", err.message);
      if (elapsed > 150000) {
        clearInterval(pollTimer);
        pollTimer = null;
        finishTurn("I stopped watching that one. It may still finish in the background.", "info");
      }
    }
  };

  pollTimer = setInterval(tick, 2500);
  setTimeout(tick, 900);
}

async function finishTurn(message, tone = "info", agents = []) {
  clearTyping();
  appendMessage("friday", message, agents);
  setCaption("");
  setHint("");
  isBusy = false;
  activeGoalId = null;
  setStatus("Ready", "ready");
  Orb.setState("idle");
  refreshFleetHealth();
  if (settings.speakReplies) {
    await speak(message);
  }
  if (tone === "error") toast(message, "error");
}

/* ------------------------------------------------------------------ */
/* Live activity socket                                                */
/* ------------------------------------------------------------------ */

let activityWs = null;
let activityRetry = null;

async function connectActivity() {
  if (activityWs && (activityWs.readyState === WebSocket.OPEN || activityWs.readyState === WebSocket.CONNECTING)) return;
  let token = null;
  try {
    token = await getToken();
  } catch (err) {
    console.warn("[FRIDAY] no control token:", err.message);
    scheduleActivityRetry();
    return;
  }

  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${proto}//${window.location.host}${BASE}/api/ws/activity?token=${encodeURIComponent(token)}`;

  try {
    activityWs = new WebSocket(url);
  } catch (err) {
    console.warn("[FRIDAY] activity socket failed:", err.message);
    scheduleActivityRetry();
    return;
  }

  activityWs.onopen = () => {
    setStatus("Live", "ready");
    clearTimeout(activityRetry);
  };

  activityWs.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }
    handleActivity(msg);
  };

  activityWs.onclose = () => {
    activityWs = null;
    scheduleActivityRetry();
  };

  activityWs.onerror = () => {
    if (activityWs) activityWs.close();
  };
}

function scheduleActivityRetry() {
  clearTimeout(activityRetry);
  activityRetry = setTimeout(connectActivity, 6000);
}

function handleActivity(msg) {
  if (!msg || typeof msg !== "object") return;

  if (msg.type === "activity") {
    const agent = normalizeAgent(msg.agent || msg.target);
    if (!agent) return;
    const ok = msg.success !== false;
    markAgent(agent, ok ? "done" : "failed", msg.directive || msg.action);
    if (agent === "friday") {
      markAgent("friday", isBusy ? "running" : "done");
    }
    return;
  }

  if (msg.type === "goal_update" || msg.type === "status") return;

  if (msg.type === "agent_status" || msg.type === "agent_batch") {
    const entries = msg.type === "agent_batch"
      ? Object.entries(msg.agents || {})
      : [[msg.agent_id || msg.agent, msg]];
    for (const [rawId, data] of entries) {
      const agent = normalizeAgent(rawId);
      if (!agent || !fleet) continue;
      const status = String(data.status || "").toLowerCase();
      fleet.updateAgent(agent, {
        status: status === "online" ? "online" : status === "error" ? "error" : status === "busy" ? "busy" : "offline",
        task: data.task || ""
      });
    }
  }
}

/* ------------------------------------------------------------------ */
/* Settings panel                                                      */
/* ------------------------------------------------------------------ */

const VOICE_OPTIONS = [
  { id: "en-IN-NeerjaNeural", label: "Neerja — English (India)" },
  { id: "en-IN-PrabhatNeural", label: "Prabhat — English (India)" },
  { id: "te-IN-ShrutiNeural", label: "Shruti — తెలుగు" },
  { id: "te-IN-MohanNeural", label: "Mohan — తెలుగు" }
];

function openPanel(panelId) {
  const panel = document.getElementById(panelId);
  if (!panel) return;
  panel.classList.add("open");
  panel.setAttribute("aria-hidden", "false");
}

function closePanel(panelId) {
  const panel = document.getElementById(panelId);
  if (!panel) return;
  panel.classList.remove("open");
  panel.setAttribute("aria-hidden", "true");
}

function bindSettings() {
  const panel = el("settingsPanel");

  el("settingsBtn")?.addEventListener("click", () => {
    const open = panel?.classList.contains("open");
    if (open) closePanel("settingsPanel");
    else openPanel("settingsPanel");
    el("settingsBtn").setAttribute("aria-expanded", String(!open));
  });

  el("settingsClose")?.addEventListener("click", () => closePanel("settingsPanel"));
  panel?.addEventListener("click", (event) => {
    if (event.target === panel) closePanel("settingsPanel");
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closePanel("settingsPanel");
  });

  /* tabs */
  document.querySelectorAll(".settings-nav button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".settings-nav button").forEach((b) => b.setAttribute("aria-selected", "false"));
      btn.setAttribute("aria-selected", "true");
      document.querySelectorAll(".tab-panels > [role='tabpanel']").forEach((p) => { p.hidden = true; });
      const target = document.getElementById("tab-" + btn.dataset.tab);
      if (target) target.hidden = false;
    });
  });

  /* voice */
  const stt = el("sttLang");
  if (stt) {
    stt.value = settings.sttLang;
    stt.addEventListener("change", () => {
      settings.sttLang = stt.value;
      if (recognition) recognition.lang = stt.value;
      saveSettings();
    });
  }

  const tts = el("ttsVoice");
  if (tts) {
    tts.innerHTML = "";
    VOICE_OPTIONS.forEach((voice) => {
      const option = document.createElement("option");
      option.value = voice.id;
      option.textContent = voice.label;
      tts.appendChild(option);
    });
    tts.value = settings.ttsVoice;
    tts.addEventListener("change", () => {
      settings.ttsVoice = tts.value;
      saveSettings();
      speak("This is how I sound now.");
    });
  }

  const speakToggle = el("speakReplies");
  if (speakToggle) {
    speakToggle.checked = settings.speakReplies;
    speakToggle.addEventListener("change", () => {
      settings.speakReplies = speakToggle.checked;
      saveSettings();
      if (!settings.speakReplies) {
        window.speechSynthesis?.cancel();
        if (currentAudio) currentAudio.pause();
      }
    });
  }

  const autoDetect = el("autoLangDetect");
  if (autoDetect) {
    autoDetect.checked = settings.autoLangDetect;
    autoDetect.addEventListener("change", () => {
      settings.autoLangDetect = autoDetect.checked;
      saveSettings();
    });
  }

  /* appearance */
  const theme = el("themeMode");
  if (theme) {
    theme.value = settings.themeMode;
    theme.addEventListener("change", () => {
      settings.themeMode = theme.value;
      applyAppearance();
      saveSettings();
    });
  }

  document.querySelectorAll(".color-picker button").forEach((btn) => {
    btn.setAttribute("aria-pressed", String(btn.dataset.color === settings.accent));
    btn.addEventListener("click", () => {
      settings.accent = btn.dataset.color;
      document.querySelectorAll(".color-picker button").forEach((b) => b.setAttribute("aria-pressed", "false"));
      btn.setAttribute("aria-pressed", "true");
      applyAppearance();
      saveSettings();
    });
  });

  const reduced = el("reducedMotion");
  if (reduced) {
    reduced.checked = settings.reducedMotion;
    reduced.addEventListener("change", () => {
      settings.reducedMotion = reduced.checked;
      applyAppearance();
      Orb.reduced = settings.reducedMotion;
      saveSettings();
    });
  }

  /* agents */
  const toggles = el("agentToggles");
  if (toggles) {
    toggles.innerHTML = "";
    const saved = JSON.parse(localStorage.getItem("friday_agent_visibility") || "{}");
    AGENTS.forEach((agent) => {
      const label = document.createElement("label");
      label.className = "agent-toggle";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = saved[agent] !== false;
      input.dataset.agent = agent;
      input.addEventListener("change", () => {
        saved[agent] = input.checked;
        localStorage.setItem("friday_agent_visibility", JSON.stringify(saved));
        const card = document.querySelector(`[data-agent-id="${agent}"]`);
        if (card) card.style.display = input.checked ? "" : "none";
      });
      const text = document.createElement("span");
      text.textContent = agent;
      label.append(input, text);
      toggles.appendChild(label);
    });
  }

  el("resetDefaults")?.addEventListener("click", () => {
    Object.assign(settings, DEFAULT_SETTINGS);
    saveSettings();
    applyAppearance();
    toast("Settings restored.", "info");
    setTimeout(() => window.location.reload(), 600);
  });
}

/* ------------------------------------------------------------------ */
/* Header controls                                                     */
/* ------------------------------------------------------------------ */

function bindHeader() {
  el("fleetToggle")?.addEventListener("click", () => {
    if (fleet && fleet.togglePanel) {
      fleet.togglePanel();
      el("fleetToggle").setAttribute("aria-expanded", String(fleet.isPanelOpen));
    } else {
      toast("Fleet panel is still loading.", "info");
    }
  });

  el("flowToggle")?.addEventListener("click", () => {
    if (flow && flow.toggle) flow.toggle();
    else toast("Flow view is still loading.", "info");
  });
}

function bindVoiceControls() {
  el("micBtn")?.addEventListener("click", toggleListening);

  el("sendBtn")?.addEventListener("click", () => {
    const input = el("textInput");
    if (input && input.value.trim()) ask(input.value.trim(), "text");
  });

  el("textInput")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      const input = el("textInput");
      if (input && input.value.trim()) ask(input.value.trim(), "text");
    }
  });

  window.addEventListener("keydown", (event) => {
    if (event.code === "Space" && event.target === document.body) {
      event.preventDefault();
      toggleListening();
    }
  });
}

/* ------------------------------------------------------------------ */
/* Clock + boot                                                        */
/* ------------------------------------------------------------------ */

function startClock() {
  const clock = el("clock");
  if (!clock) return;
  const paint = () => {
    clock.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };
  paint();
  setInterval(paint, 15000);
}

async function boot() {
  cacheUI();
  loadSettings();
  applyAppearance();

  const canvas = el("orbCanvas");
  if (canvas) {
    Orb.init(canvas);
    Orb.reduced = settings.reducedMotion || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.__fridayOrb = Orb;
  }

  setStatus("Waking up…", "processing");
  setHint("");
  setCaption("");

  bindHeader();
  bindVoiceControls();
  bindSettings();
  startClock();

  /* components, isolated so one failure cannot blank the interface */
  try { await initFleet(); } catch (err) { console.warn("[FRIDAY] fleet unavailable:", err.message); }
  try { await initFlow(); } catch (err) { console.warn("[FRIDAY] flow unavailable:", err.message); }

  if (fleet) {
    window.__fridayFleetDebug = () => Object.fromEntries([...fleet.agentStates].map(([k, v]) => [k, v.status]));
    refreshFleetHealth();
    setInterval(refreshFleetHealth, 25000);
  }

  const greeting = "I'm here. What do you want to get done?";
  setStatus("Ready", "ready");
  document.body.classList.add("friday-ready");

  setTimeout(() => {
    appendMessage("friday", greeting);
  }, 350);

  connectActivity();
  setInterval(connectActivity, 30000);

  /* live amplitude feed for the orb */
  setInterval(() => {
    if (Orb.state === "speaking") Orb.setAmplitude(currentAmplitude());
  }, 60);

  /* honest connection indicator */
  setInterval(async () => {
    if (activityWs && activityWs.readyState === WebSocket.OPEN) return;
    if (isBusy) return;
    try {
      const res = await fetch(BASE + "/health", { cache: "no-store" });
      setStatus(res.ok ? "Reconnecting" : "Offline", res.ok ? "processing" : "error");
    } catch {
      setStatus("Offline", "error");
    }
  }, 15000);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot, { once: true });
} else {
  boot();
}
