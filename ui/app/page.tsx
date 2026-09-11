"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import * as THREE from "three";
import { HandLandmarker, FilesetResolver } from "@mediapipe/tasks-vision";

interface TelemetryData {
  cpu_percent: number;
  cpu_cores: number;
  ram_percent: number;
  ram_total_gb: number;
  ram_used_gb: number;
  ram_avail_gb: number;
  os: string;
  operator: string;
}

interface SpecialistAgent {
  id: string;
  name: string;
  role: string;
  icon: string;
  status: string;
  desc: string;
}

const SPECIALIST_AGENTS: SpecialistAgent[] = [
  { id: "inference", name: "Inference", role: "Cloud AI Gateway", icon: "⚡", status: "ONLINE", desc: "10-specialist consensus engine" },
  { id: "stratex", name: "Stratex", role: "Algorithmic Trading", icon: "📈", status: "ONLINE", desc: "24/7 Binance Futures trading & risk shield" },
  { id: "memora", name: "Memora", role: "Persistent Memory", icon: "🧠", status: "ONLINE", desc: "Turso 9GB cloud vector memory fabric" },
  { id: "intelx", name: "IntelX", role: "Macro Research", icon: "🔍", status: "ONLINE", desc: "Real-time market & sentiment intelligence" },
  { id: "futuris", name: "Futuris", role: "Predictive Forecaster", icon: "🔮", status: "ONLINE", desc: "Probabilistic volatility & trend forecaster" },
  { id: "cortex", name: "Cortex", role: "Web Operations", icon: "🌐", status: "ONLINE", desc: "Autonomous web scraper & browser crawler" },
  { id: "forge", name: "Forge", role: "Software Engineering", icon: "🛠️", status: "ONLINE", desc: "Autonomous code synthesis & test runner" },
  { id: "sentinel", name: "Sentinel", role: "Cybersecurity Shield", icon: "🛡️", status: "ONLINE", desc: "Zero-trust capability gating & threat defense" },
];

// MediaPipe 21 Hand Landmark Bones (Connections)
const HAND_CONNECTIONS: [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 4],       // Thumb
  [0, 5], [5, 6], [6, 7], [7, 8],       // Index
  [5, 9], [9, 10], [10, 11], [11, 12],  // Middle
  [9, 13], [13, 14], [14, 15], [15, 16],// Ring
  [13, 17], [17, 18], [18, 19], [19, 20], [0, 17], // Pinky & Palm
];

export default function FridayHolographicCore() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const overlayCanvasRef = useRef<HTMLCanvasElement>(null);

  // Core System States
  const [status, setStatus] = useState("FRIDAY CORE ONLINE // ALL SYSTEMS NOMINAL");
  const [lastResponse, setLastResponse] = useState<string | null>(null);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [screenshotModal, setScreenshotModal] = useState<string | null>(null);
  const [specsModal, setSpecsModal] = useState<TelemetryData | null>(null);
  const [leftGesture, setLeftGesture] = useState("Scanning Left Hand...");
  const [rightGesture, setRightGesture] = useState("Scanning Right Hand...");
  const [activeHandsCount, setActiveHandsCount] = useState(0);
  const [isProcessing, setIsProcessing] = useState(false);
  const [adbStatus, setAdbStatus] = useState("CHECKING ADB...");
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [isListening, setIsListening] = useState(false);
  const [voiceTranscript, setVoiceTranscript] = useState("");
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  const [telemetry, setTelemetry] = useState<TelemetryData>({
    cpu_percent: 18.5,
    cpu_cores: 12,
    ram_percent: 64.2,
    ram_total_gb: 16.0,
    ram_used_gb: 10.2,
    ram_avail_gb: 5.8,
    os: "Windows 11 x64",
    operator: "Surendra",
  });

  const wsRef = useRef<WebSocket | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const recognitionRef = useRef<any>(null);
  const isSpeakingRef = useRef<boolean>(false);
  const silenceTimerRef = useRef<any>(null);

  // Dynamic API host based on browser window location
  const getApiUrl = (endpoint: string) => {
    const host = typeof window !== "undefined" ? window.location.hostname || "127.0.0.1" : "127.0.0.1";
    return `http://${host}:9000${endpoint}`;
  };

  const getWsUrl = (endpoint: string) => {
    const host = typeof window !== "undefined" ? window.location.hostname || "127.0.0.1" : "127.0.0.1";
    return `ws://${host}:9000${endpoint}`;
  };

  // HIGH-CLARITY STUDIO FEMALE VOICE SYNTHESIS (Natural / Crystal Clear FRIDAY Voice)
  const speakFemaleVoice = useCallback((text: string) => {
    if (!soundEnabled || typeof window === "undefined" || !("speechSynthesis" in window)) return;
    try {
      window.speechSynthesis.cancel();
      isSpeakingRef.current = true;
      setIsSpeaking(true);

      const utterance = new SpeechSynthesisUtterance(text);
      const voices = window.speechSynthesis.getVoices();

      // Prioritize natural studio-grade online voices (Windows 11 Natural Neural voices)
      let naturalFemale = voices.find((v) =>
        v.lang.startsWith("en") &&
        (v.name.includes("Natural") || v.name.includes("Online")) &&
        (v.name.includes("Jenny") || v.name.includes("Aria") || v.name.includes("Ava") || v.name.includes("Zira"))
      );

      // Fallback to high-quality system voices
      if (!naturalFemale) {
        naturalFemale = voices.find((v) =>
          v.name.includes("Zira") ||
          (v.name.includes("Google") && v.name.toLowerCase().includes("us english")) ||
          v.name.includes("Hazel") ||
          v.name.includes("Eva") ||
          (v.lang.startsWith("en") && v.name.toLowerCase().includes("female"))
        );
      }

      if (naturalFemale) utterance.voice = naturalFemale;
      // Pitch 1.0 delivers authentic, natural human warmth without metallic pitching
      utterance.pitch = 1.0;
      utterance.rate = 1.02;
      utterance.volume = 1.0;

      utterance.onend = () => {
        isSpeakingRef.current = false;
        setIsSpeaking(false);
      };

      utterance.onerror = () => {
        isSpeakingRef.current = false;
        setIsSpeaking(false);
      };

      window.speechSynthesis.speak(utterance);
    } catch (e) {
      console.warn("Speech synthesis error:", e);
      isSpeakingRef.current = false;
      setIsSpeaking(false);
    }
  }, [soundEnabled]);

  // Web Audio Synthesizer for Cybernetic UI SFX
  const playSound = useCallback((type: "click" | "chime" | "whoosh") => {
    if (!soundEnabled) return;
    try {
      if (!audioCtxRef.current) {
        audioCtxRef.current = new (window.AudioContext || (window as any).webkitAudioContext)();
      }
      const ctx = audioCtxRef.current;
      if (ctx.state === "suspended") ctx.resume();

      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);

      const now = ctx.currentTime;
      if (type === "click") {
        osc.type = "sine";
        osc.frequency.setValueAtTime(880, now);
        osc.frequency.exponentialRampToValueAtTime(1320, now + 0.04);
        gain.gain.setValueAtTime(0.08, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.04);
        osc.start(now);
        osc.stop(now + 0.04);
      } else if (type === "chime") {
        osc.type = "triangle";
        osc.frequency.setValueAtTime(587.33, now);
        osc.frequency.setValueAtTime(880, now + 0.08);
        gain.gain.setValueAtTime(0.1, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25);
        osc.start(now);
        osc.stop(now + 0.25);
      } else if (type === "whoosh") {
        osc.type = "sine";
        osc.frequency.setValueAtTime(320, now);
        osc.frequency.exponentialRampToValueAtTime(740, now + 0.12);
        gain.gain.setValueAtTime(0.07, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.12);
        osc.start(now);
        osc.stop(now + 0.12);
      }
    } catch {}
  }, [soundEnabled]);

  // Dual-Hand physics ref shared with 3D scene
  const dualHandStateRef = useRef({
    handCount: 0,
    hand1: { detected: false, x: 0.5, y: 0.5, isPinching: false, isOpen: false, side: "Left" },
    hand2: { detected: false, x: 0.5, y: 0.5, isPinching: false, isOpen: false, side: "Right" },
    dualDistance: 0.5,
    dualExpansion: 1.0,
  });

  // Send Command to Friday Backend
  const sendCommand = useCallback(async (command: string) => {
    const trimmed = (command || "").trim();
    if (!trimmed) return;

    playSound("click");
    setIsProcessing(true);
    setStatus(`EXECUTING // ${trimmed.toUpperCase()}`);
    try {
      const res = await fetch(getApiUrl("/api/command"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: trimmed }),
      });
      const data = await res.json();
      playSound("chime");
      setLastResponse(data.reply);
      setStatus("TASK COMPLETE // READY");

      // Speak response with FRIDAY crystal-clear female voice
      if (data.reply) {
        speakFemaleVoice(data.reply);
      }

      if (data.metadata && data.metadata.action === "screenshot" && data.metadata.image_b64) {
        setScreenshotModal(data.metadata.image_b64);
      } else if (data.metadata && data.metadata.action === "specs" && data.metadata.telemetry) {
        setSpecsModal({ ...telemetry, ...data.metadata.telemetry });
      }
    } catch {
      const errReply = "Connecting to FRIDAY Core on port 9000. Ensure backend server is active.";
      setLastResponse(errReply);
      setStatus("STANDBY // READY");
    } finally {
      setIsProcessing(false);
      setVoiceTranscript("");
    }
  }, [playSound, speakFemaleVoice, telemetry]);

  // High-Quality Debounced Voice Recognition (No Partial Truncations)
  const toggleListening = useCallback(() => {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert("Speech recognition is supported in Google Chrome and Microsoft Edge.");
      return;
    }

    if (isListening) {
      if (recognitionRef.current) {
        try {
          recognitionRef.current.stop();
        } catch {}
      }
      setIsListening(false);
      setVoiceTranscript("");
      playSound("click");
    } else {
      try {
        const recognition = new SpeechRecognition();
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.lang = "en-US";

        recognition.onstart = () => {
          setIsListening(true);
          playSound("chime");
          setStatus("VOICE LISTENING // SPEAK DIRECTIVE");
        };

        recognition.onresult = (event: any) => {
          // Do not listen to own voice output
          if (isSpeakingRef.current) return;

          let interim = "";
          let final = "";

          for (let i = event.resultIndex; i < event.results.length; ++i) {
            if (event.results[i].isFinal) {
              final += event.results[i][0].transcript;
            } else {
              interim += event.results[i][0].transcript;
            }
          }

          const currentText = (final || interim).trim();
          if (currentText) {
            setVoiceTranscript(currentText);
          }

          // When final sentence or clear pause detected, dispatch complete command
          if (final.trim()) {
            if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
            silenceTimerRef.current = setTimeout(() => {
              sendCommand(final.trim());
              setVoiceTranscript("");
            }, 600);
          } else if (interim.trim().length > 3) {
            // Buffer speech for 1.3 seconds of silence before committing
            if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
            silenceTimerRef.current = setTimeout(() => {
              if (interim.trim().length > 2) {
                sendCommand(interim.trim());
                setVoiceTranscript("");
              }
            }, 1400);
          }
        };

        recognition.onerror = (e: any) => {
          console.warn("Speech recognition error:", e);
          if (e.error !== "no-speech") {
            setIsListening(false);
          }
        };

        recognition.onend = () => {
          // Keep listening active unless explicitly toggled off
          if (isListening && !isSpeakingRef.current) {
            try {
              recognition.start();
            } catch {}
          }
        };

        recognitionRef.current = recognition;
        recognition.start();
      } catch (e) {
        console.warn("Speech init error:", e);
        setIsListening(false);
      }
    }
  }, [isListening, playSound, sendCommand]);

  // Fetch Live Telemetry and ADB Status
  useEffect(() => {
    const fetchTelemetry = () => {
      fetch(getApiUrl("/api/system_telemetry"))
        .then((r) => r.json())
        .then((data) => {
          if (data.status === "ok") {
            setTelemetry(data);
          }
        })
        .catch(() => {});
    };

    const fetchAdb = () => {
      fetch(getApiUrl("/api/android"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "info" }),
      })
        .then((r) => r.json())
        .then((d) => {
          if (d.success && d.devices && d.devices.length > 0) {
            setAdbStatus(`ADB CONNECTED (${d.devices.length} DEVICE)`);
          } else {
            setAdbStatus("ADB STANDBY (CONNECT PHONE VIA USB)");
          }
        })
        .catch(() => setAdbStatus("BACKEND CONNECTING"));
    };

    fetchTelemetry();
    fetchAdb();
    const interval = setInterval(fetchTelemetry, 2500);
    return () => clearInterval(interval);
  }, []);

  // Three.js Arc Reactor Core (Exact Match to Reference Video with Stable Gyroscopic Tilt)
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });

    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    camera.position.z = 8.5;

    // Master Group for 3D physics & transformations
    const masterGroup = new THREE.Group();
    scene.add(masterGroup);

    // 1. Central Plasma Core (Glowing nested energy sphere with Additive Blending)
    const coreMat = new THREE.MeshBasicMaterial({
      color: 0x00f0ff,
      transparent: true,
      opacity: 0.92,
      blending: THREE.AdditiveBlending,
    });
    const coreGeo = new THREE.SphereGeometry(1.0, 32, 32);
    const coreOrb = new THREE.Mesh(coreGeo, coreMat);
    masterGroup.add(coreOrb);

    // Inner White Energy Singularity
    const singMat = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.98,
      blending: THREE.AdditiveBlending,
    });
    const singOrb = new THREE.Mesh(new THREE.SphereGeometry(0.55, 24, 24), singMat);
    masterGroup.add(singOrb);

    // Outer Translucent Corona Halo (Icosahedron Wireframe)
    const coronaMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      wireframe: true,
      transparent: true,
      opacity: 0.45,
      blending: THREE.AdditiveBlending,
    });
    const coronaOrb = new THREE.Mesh(new THREE.IcosahedronGeometry(1.6, 2), coronaMat);
    masterGroup.add(coronaOrb);

    // 2. Gyroscopic Concentric Rings with FIXED STABLE TILTS (Never flips edge-on into vertical rods!)
    // Ring 1: Outer Cyan Ring (Saturn's Ring tilt: rotation.x = 1.15)
    const ringMat1 = new THREE.MeshBasicMaterial({
      color: 0x00f0ff,
      wireframe: true,
      transparent: true,
      opacity: 0.7,
      blending: THREE.AdditiveBlending,
    });
    const ring1 = new THREE.Mesh(new THREE.TorusGeometry(3.5, 0.045, 16, 80), ringMat1);
    ring1.rotation.x = 1.15;
    masterGroup.add(ring1);

    // Ring 2: Mid Segmented Ring (Electric Purple: rotation.x = -0.95, rotation.y = 0.35)
    const ringMat2 = new THREE.MeshBasicMaterial({
      color: 0xa855f7,
      wireframe: true,
      transparent: true,
      opacity: 0.65,
      blending: THREE.AdditiveBlending,
    });
    const ring2 = new THREE.Mesh(new THREE.TorusGeometry(2.65, 0.05, 16, 64), ringMat2);
    ring2.rotation.x = -0.95;
    ring2.rotation.y = 0.35;
    masterGroup.add(ring2);

    // Ring 3: Inner High-Flux Dial (Sky Blue)
    const ringMat3 = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      wireframe: true,
      transparent: true,
      opacity: 0.8,
      blending: THREE.AdditiveBlending,
    });
    const ring3 = new THREE.Mesh(new THREE.TorusGeometry(1.95, 0.04, 16, 48), ringMat3);
    ring3.rotation.x = 0.8;
    ring3.rotation.y = -0.4;
    masterGroup.add(ring3);

    // 3. Radial Frequency Equalizer Waveform Bars (Equatorial ring of 48 oscillating bars)
    const waveBarCount = 48;
    const waveBars: THREE.Mesh[] = [];
    const waveGroup = new THREE.Group();
    masterGroup.add(waveGroup);

    const barGeo = new THREE.CylinderGeometry(0.02, 0.02, 0.45, 8);
    const barMat = new THREE.MeshBasicMaterial({
      color: 0x00f0ff,
      transparent: true,
      opacity: 0.8,
      blending: THREE.AdditiveBlending,
    });

    for (let i = 0; i < waveBarCount; i++) {
      const angle = (i / waveBarCount) * Math.PI * 2;
      const bar = new THREE.Mesh(barGeo, barMat);
      const radius = 2.15;
      bar.position.set(Math.cos(angle) * radius, Math.sin(angle) * radius, 0);
      bar.rotation.z = angle + Math.PI / 2;
      waveGroup.add(bar);
      waveBars.push(bar);
    }

    // 4. Energy Deflector Shield (Hexagonal Sphere activated on Radiant Palm gesture)
    const shieldMat = new THREE.MeshBasicMaterial({
      color: 0x00f0ff,
      wireframe: true,
      transparent: true,
      opacity: 0.0,
      blending: THREE.AdditiveBlending,
    });
    const shieldOrb = new THREE.Mesh(new THREE.IcosahedronGeometry(4.2, 2), shieldMat);
    masterGroup.add(shieldOrb);

    // 5. Cosmic Particle Matrix (1,400 cyan and purple particles)
    const particleCount = 1400;
    const particleGeo = new THREE.BufferGeometry();
    const posArray = new Float32Array(particleCount * 3);
    const colArray = new Float32Array(particleCount * 3);

    for (let i = 0; i < particleCount * 3; i += 3) {
      const radius = 3.5 + Math.random() * 14.0;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(Math.random() * 2 - 1);

      posArray[i] = radius * Math.sin(phi) * Math.cos(theta);
      posArray[i + 1] = radius * Math.sin(phi) * Math.sin(theta);
      posArray[i + 2] = radius * Math.cos(phi);

      if (Math.random() > 0.4) {
        colArray[i] = 0.0;
        colArray[i + 1] = 0.94;
        colArray[i + 2] = 1.0;
      } else {
        colArray[i] = 0.65;
        colArray[i + 1] = 0.33;
        colArray[i + 2] = 0.96;
      }
    }

    particleGeo.setAttribute("position", new THREE.BufferAttribute(posArray, 3));
    particleGeo.setAttribute("color", new THREE.BufferAttribute(colArray, 3));

    const particleMat = new THREE.PointsMaterial({
      size: 0.055,
      vertexColors: true,
      transparent: true,
      opacity: 0.7,
      blending: THREE.AdditiveBlending,
    });

    const particleCloud = new THREE.Points(particleGeo, particleMat);
    scene.add(particleCloud);

    // 6. Smooth Animation Loop
    let frameId: number;
    let running = true;

    const animate = () => {
      if (!running) return;

      const now = performance.now() * 0.001;
      const state = dualHandStateRef.current;

      // Axial rotations with FIXED tilts (Smooth celestial rotation without tumbling!)
      ring1.rotation.z = now * 0.25;
      ring1.rotation.y = Math.sin(now * 0.6) * 0.12;

      ring2.rotation.z = -now * 0.35;
      ring2.rotation.y = 0.35 + Math.cos(now * 0.5) * 0.1;

      ring3.rotation.z = now * 0.45;
      waveGroup.rotation.z = -now * 0.2;

      coronaOrb.rotation.y = now * 0.18;
      coronaOrb.rotation.x = now * 0.12;

      particleCloud.rotation.y = now * 0.03;

      // Dynamic Radial Waveform Bars (Gentle harmonic oscillation)
      for (let i = 0; i < waveBarCount; i++) {
        const s = 0.5 + Math.sin(now * 6 + i * 0.35) * 0.4 + Math.cos(now * 9 + i * 0.7) * 0.2;
        waveBars[i].scale.set(1, Math.max(0.15, s), 1);
      }

      // Dual-Hand Optical Interaction
      if (state.handCount >= 2 && state.hand1.detected && state.hand2.detected) {
        const midX = ((state.hand1.x + state.hand2.x) / 2 - 0.5) * 5.0;
        const midY = (-((state.hand1.y + state.hand2.y) / 2 - 0.5)) * 3.5;
        masterGroup.position.x += (midX - masterGroup.position.x) * 0.1;
        masterGroup.position.y += (midY - masterGroup.position.y) * 0.1;

        const targetScale = Math.min(2.0, Math.max(0.7, state.dualDistance * 3.0));
        masterGroup.scale.lerp(new THREE.Vector3(targetScale, targetScale, targetScale), 0.1);

        if (state.hand1.isOpen && state.hand2.isOpen) {
          shieldMat.opacity += (0.45 - shieldMat.opacity) * 0.15;
          shieldOrb.rotation.y += 0.03;
        } else {
          shieldMat.opacity += (0.0 - shieldMat.opacity) * 0.15;
        }

        if (state.hand1.isPinching || state.hand2.isPinching) {
          coreOrb.scale.lerp(new THREE.Vector3(0.45, 0.45, 0.45), 0.15);
        } else {
          const corePulse = 1 + Math.sin(now * 4) * 0.08;
          coreOrb.scale.lerp(new THREE.Vector3(corePulse, corePulse, corePulse), 0.1);
        }
      } else if (state.handCount === 1 && state.hand1.detected) {
        const targetX = (state.hand1.x - 0.5) * 4.5;
        const targetY = -(state.hand1.y - 0.5) * 3.0;
        masterGroup.position.x += (targetX - masterGroup.position.x) * 0.08;
        masterGroup.position.y += (targetY - masterGroup.position.y) * 0.08;

        if (state.hand1.isPinching) {
          masterGroup.scale.lerp(new THREE.Vector3(0.75, 0.75, 0.75), 0.1);
        } else {
          masterGroup.scale.lerp(new THREE.Vector3(1.1, 1.1, 1.1), 0.08);
        }
        shieldMat.opacity += (0.0 - shieldMat.opacity) * 0.15;
      } else {
        masterGroup.position.x += (0 - masterGroup.position.x) * 0.05;
        masterGroup.position.y += (0 - masterGroup.position.y) * 0.05;

        const pulse = 1 + Math.sin(now * 2.5) * 0.04;
        masterGroup.scale.set(pulse, pulse, pulse);
        shieldMat.opacity += (0.0 - shieldMat.opacity) * 0.15;
      }

      renderer.render(scene, camera);
      frameId = requestAnimationFrame(animate);
    };

    frameId = requestAnimationFrame(animate);

    const handleResize = () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    };
    window.addEventListener("resize", handleResize);

    return () => {
      running = false;
      cancelAnimationFrame(frameId);
      window.removeEventListener("resize", handleResize);
      renderer.dispose();
      particleGeo.dispose();
      particleMat.dispose();
      ring1.geometry.dispose();
      ringMat1.dispose();
      ring2.geometry.dispose();
      ringMat2.dispose();
      ring3.geometry.dispose();
      ringMat3.dispose();
      coreGeo.dispose();
      coreMat.dispose();
    };
  }, []);

  // MediaPipe DUAL-HAND Tracking (Right Card with FULL 21-Bone Skeleton)
  useEffect(() => {
    let handLandmarker: HandLandmarker | null = null;
    let animationFrameId: number;
    let active = true;

    const initializeMediaPipe = async () => {
      try {
        const vision = await FilesetResolver.forVisionTasks(
          "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.3/wasm"
        );
        if (!active) return;

        handLandmarker = await HandLandmarker.createFromOptions(vision, {
          baseOptions: {
            modelAssetPath:
              "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
            delegate: "GPU",
          },
          runningMode: "VIDEO",
          numHands: 2,
        });

        if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
          const stream = await navigator.mediaDevices.getUserMedia({
            video: { width: 640, height: 480, frameRate: { ideal: 60, max: 60 } },
          });
          if (!active) return;

          if (videoRef.current) {
            videoRef.current.srcObject = stream;
            videoRef.current.onloadeddata = () => {
              if (active) predictWebcam();
            };
            if (videoRef.current.readyState >= 2) {
              predictWebcam();
            }
          }
        }
      } catch (err) {
        console.warn("MediaPipe camera init skipped:", err);
      }
    };

    let lastVideoTime = -1;
    let lastDetectTime = 0;
    let lastLeftSwipe = 0;
    let lastRightSwipe = 0;

    const predictWebcam = () => {
      if (!active) return;

      const now = performance.now();
      if (videoRef.current && handLandmarker && videoRef.current.readyState >= 2) {
        if (videoRef.current.currentTime !== lastVideoTime && now - lastDetectTime >= 32) {
          lastVideoTime = videoRef.current.currentTime;
          lastDetectTime = now;

          try {
            const results = handLandmarker.detectForVideo(videoRef.current, now);

            const overlay = overlayCanvasRef.current;
            const ctx = overlay ? overlay.getContext("2d") : null;
            if (ctx && overlay) {
              ctx.clearRect(0, 0, overlay.width, overlay.height);
            }

            if (results && results.landmarks && results.landmarks.length > 0) {
              const count = results.landmarks.length;
              setActiveHandsCount(count);

              const ts = Date.now();
              let leftFound = false;
              let rightFound = false;
              let h1 = { detected: false, x: 0.5, y: 0.5, isPinching: false, isOpen: false, side: "Left" };
              let h2 = { detected: false, x: 0.5, y: 0.5, isPinching: false, isOpen: false, side: "Right" };

              for (let i = 0; i < count; i++) {
                const landmarks = results.landmarks[i];
                const wrist = landmarks[0];
                const thumbTip = landmarks[4];
                const indexTip = landmarks[8];
                const middleTip = landmarks[12];

                // Mirrored coordinates for selfie video
                const mirroredX = 1 - indexTip.x;
                const mirroredY = indexTip.y;

                const pinchDist = Math.hypot(thumbTip.x - indexTip.x, thumbTip.y - indexTip.y);
                const isPinching = pinchDist < 0.085;

                const handSpan = Math.hypot(middleTip.x - wrist.x, middleTip.y - wrist.y);
                const isOpen = handSpan > 0.35;

                let gestureDesc = "Tracking Coordinates";
                if (isPinching) gestureDesc = "Singularity Pinch";
                else if (isOpen) gestureDesc = "Radiant Palm";

                const isLeftHand = mirroredX < 0.5;

                if (isLeftHand) {
                  leftFound = true;
                  h1 = { detected: true, x: mirroredX, y: mirroredY, isPinching, isOpen, side: "Left" };
                  setLeftGesture(`Left: ${gestureDesc}`);

                  // Left Hand Swipe to left edge -> Launches Notepad
                  if (mirroredX < 0.20 && ts - lastLeftSwipe > 2500) {
                    lastLeftSwipe = ts;
                    playSound("whoosh");
                    setLeftGesture("Left Swipe ➔ Launching Notepad");
                    sendCommand("open notepad");
                  }
                } else {
                  rightFound = true;
                  h2 = { detected: true, x: mirroredX, y: mirroredY, isPinching, isOpen, side: "Right" };
                  setRightGesture(`Right: ${gestureDesc}`);

                  // Right Hand Swipe to right edge -> Launches Chrome
                  if (mirroredX > 0.80 && ts - lastRightSwipe > 2500) {
                    lastRightSwipe = ts;
                    playSound("whoosh");
                    setRightGesture("Right Swipe ➔ Launching Chrome");
                    sendCommand("open chrome");
                  }
                }

                // Draw FULL 21-BONE SKELETON (Matching Reference Video)
                if (ctx && overlay) {
                  const boneColor = isLeftHand ? "rgba(0, 240, 255, 0.75)" : "rgba(192, 132, 252, 0.75)";
                  const jointColor = isLeftHand ? "#00f0ff" : "#c084fc";

                  // 1. Draw Connecting Bones
                  ctx.strokeStyle = boneColor;
                  ctx.lineWidth = 2.5;
                  ctx.lineCap = "round";

                  for (const [startIdx, endIdx] of HAND_CONNECTIONS) {
                    const startPt = landmarks[startIdx];
                    const endPt = landmarks[endIdx];
                    if (startPt && endPt) {
                      ctx.beginPath();
                      ctx.moveTo((1 - startPt.x) * overlay.width, startPt.y * overlay.height);
                      ctx.lineTo((1 - endPt.x) * overlay.width, endPt.y * overlay.height);
                      ctx.stroke();
                    }
                  }

                  // 2. Draw Joint Nodes
                  ctx.fillStyle = jointColor;
                  for (const pt of landmarks) {
                    const cx = (1 - pt.x) * overlay.width;
                    const cy = pt.y * overlay.height;
                    ctx.beginPath();
                    ctx.arc(cx, cy, 3, 0, 2 * Math.PI);
                    ctx.fill();
                  }

                  // 3. Target Reticle on Index Fingertip
                  const targetX = mirroredX * overlay.width;
                  const targetY = mirroredY * overlay.height;
                  ctx.strokeStyle = jointColor;
                  ctx.lineWidth = 1.5;
                  ctx.beginPath();
                  ctx.arc(targetX, targetY, isPinching ? 6 : 14, 0, 2 * Math.PI);
                  ctx.stroke();
                }
              }

              if (!leftFound) setLeftGesture("Scanning Left Hand...");
              if (!rightFound) setRightGesture("Scanning Right Hand...");

              let dist = 0.5;
              if (leftFound && rightFound) {
                dist = Math.hypot(h1.x - h2.x, h1.y - h2.y);
              }

              dualHandStateRef.current = {
                handCount: count,
                hand1: leftFound ? h1 : h2,
                hand2: rightFound ? h2 : h1,
                dualDistance: dist,
                dualExpansion: dist * 2.5,
              };
            } else {
              setActiveHandsCount(0);
              dualHandStateRef.current.handCount = 0;
              setLeftGesture("Scanning Left Hand...");
              setRightGesture("Scanning Right Hand...");
            }
          } catch (e) {
            console.error("Dual tracking frame error:", e);
          }
        }
      }
      animationFrameId = window.requestAnimationFrame(predictWebcam);
    };

    initializeMediaPipe();

    return () => {
      active = false;
      if (animationFrameId) window.cancelAnimationFrame(animationFrameId);
      if (handLandmarker) handLandmarker.close();
    };
  }, [playSound, sendCommand]);

  return (
    <main className="relative w-screen h-screen select-none bg-[#020617] overflow-hidden">
      {/* Subtle Scanline Overlay */}
      <div className="scanline" />

      {/* 3D Holographic Arc Reactor WebGL Scene */}
      <div id="canvas-container">
        <canvas ref={canvasRef} className="w-full h-full block" />
      </div>

      {/* Futuristic HUD Interface Layer */}
      <div id="ui-layer">
        {/* TOP HEADER */}
        <header className="flex justify-between items-center w-full">
          <div>
            <div className="flex items-center gap-3">
              <div className="w-3 h-3 rounded-full bg-cyan-400 shadow-[0_0_14px_#00f0ff] animate-pulse" />
              <h1 className="text-3xl hud-title">F . R . I . D . A . Y .</h1>
            </div>
            <p className="hud-sub mt-0.5 tracking-widest">
              SURENDRA&apos;S AUTONOMOUS INTELLIGENCE // DUAL-HAND HOLOGRAPHIC CORE v3.5
            </p>
          </div>

          <div className="flex items-center gap-2.5">
            <div className="hud-pill text-emerald-400 border-emerald-500/40">
              <span className="pulse-dot" />
              <span>{status}</span>
            </div>
            <div className="hud-pill text-purple-400 border-purple-500/40">
              <span>{activeHandsCount} HANDS TRACKED</span>
            </div>
            <div className="hud-pill text-sky-400 border-sky-500/40">
              <span>{adbStatus}</span>
            </div>
            <button
              onClick={toggleListening}
              className={`hud-pill cursor-pointer pointer-events-auto transition ${
                isListening
                  ? "text-red-400 border-red-500/60 bg-red-950/50 animate-pulse shadow-[0_0_18px_rgba(239,68,68,0.5)]"
                  : "text-emerald-400 border-emerald-500/40 hover:bg-emerald-950/60"
              }`}
              title="Toggle FRIDAY Voice Listening"
            >
              {isListening ? "🎙️ LISTENING..." : "🎤 VOICE: ON"}
            </button>
            <button
              onClick={() => {
                setSoundEnabled(!soundEnabled);
                playSound("click");
              }}
              className="hud-pill text-cyan-300 border-cyan-500/40 hover:bg-cyan-950/60 cursor-pointer pointer-events-auto transition"
              title="Toggle Audio Feedback"
            >
              {soundEnabled ? "🔊 AUDIO: ON" : "🔇 AUDIO: OFF"}
            </button>
          </div>
        </header>

        {/* FRIDAY RESPONSE BANNER */}
        {lastResponse && (
          <div className="w-full flex justify-center pointer-events-auto z-50">
            <div className="glass-hud border-cyan-400/50 px-6 py-3 max-w-2xl flex items-center justify-between gap-4 shadow-[0_0_35px_rgba(0,240,255,0.25)] animate-in fade-in slide-in-from-top-4 duration-300">
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5">
                  <div className="w-2.5 h-2.5 rounded-full bg-cyan-400 animate-ping" />
                  <span className="text-cyan-400 font-bold text-xs tracking-wider uppercase font-mono">FRIDAY:</span>
                </div>
                <span className="text-sky-100 text-sm font-medium leading-relaxed">{lastResponse}</span>
              </div>
              {isSpeaking && (
                <div className="flex items-center gap-1 h-4 px-2">
                  <div className="w-1 bg-cyan-400 rounded-full animate-pulse h-4" />
                  <div className="w-1 bg-sky-300 rounded-full animate-pulse h-3" />
                  <div className="w-1 bg-cyan-400 rounded-full animate-pulse h-5" />
                  <div className="w-1 bg-sky-300 rounded-full animate-pulse h-2" />
                </div>
              )}
              <button
                onClick={() => setLastResponse(null)}
                className="text-cyan-400 hover:text-white text-xs font-mono font-bold px-2 py-0.5 rounded border border-cyan-500/30 hover:border-cyan-400 transition"
              >
                ✕
              </button>
            </div>
          </div>
        )}

        {/* SCREENSHOT MODAL */}
        {screenshotModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md pointer-events-auto p-8">
            <div className="holo-modal rounded-xl max-w-4xl w-full p-6 flex flex-col gap-4 border border-cyan-400/60 shadow-[0_0_50px_rgba(0,240,255,0.3)]">
              <div className="flex justify-between items-center border-b border-cyan-500/30 pb-3">
                <div className="flex items-center gap-2">
                  <span className="text-cyan-400 font-bold text-base tracking-widest font-mono">
                    DESKTOP SCREENSHOT // LIVE CAPTURE
                  </span>
                </div>
                <button
                  onClick={() => setScreenshotModal(null)}
                  className="hud-btn bg-cyan-950 text-cyan-300 hover:text-white px-3 py-1 text-xs font-bold"
                >
                  CLOSE [✕]
                </button>
              </div>
              <div className="relative rounded-lg overflow-hidden border border-cyan-500/40 bg-black/60 flex justify-center items-center max-h-[70vh]">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={screenshotModal} alt="Desktop Capture" className="object-contain max-h-[68vh] w-auto rounded" />
              </div>
            </div>
          </div>
        )}

        {/* SPECS MODAL */}
        {specsModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md pointer-events-auto p-8">
            <div className="holo-modal rounded-xl max-w-2xl w-full p-6 flex flex-col gap-5 border border-sky-400/60 shadow-[0_0_50px_rgba(56,189,248,0.3)] font-mono">
              <div className="flex justify-between items-center border-b border-sky-500/30 pb-3">
                <span className="text-sky-400 font-bold text-base tracking-widest uppercase">
                  SYSTEM TELEMETRY // SPECIFICATIONS
                </span>
                <button
                  onClick={() => setSpecsModal(null)}
                  className="hud-btn bg-sky-950 text-sky-300 hover:text-white px-3 py-1 text-xs font-bold"
                >
                  CLOSE [✕]
                </button>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="glass-hud p-4 rounded-lg flex flex-col gap-1">
                  <span className="text-xs text-sky-400/70 uppercase">CPU Utilization</span>
                  <span className="text-2xl text-cyan-300 font-bold">{specsModal.cpu_percent}%</span>
                  <span className="text-xs text-sky-200/60">{specsModal.cpu_cores} Logical Cores</span>
                </div>
                <div className="glass-hud p-4 rounded-lg flex flex-col gap-1">
                  <span className="text-xs text-purple-400/70 uppercase">RAM Utilization</span>
                  <span className="text-2xl text-purple-300 font-bold">{specsModal.ram_percent}%</span>
                  <span className="text-xs text-purple-200/60">
                    {specsModal.ram_used_gb} GB / {specsModal.ram_total_gb} GB
                  </span>
                </div>
                <div className="glass-hud p-4 rounded-lg flex flex-col gap-1">
                  <span className="text-xs text-sky-400/70 uppercase">Operating System</span>
                  <span className="text-sm text-sky-200 font-semibold">{specsModal.os}</span>
                </div>
                <div className="glass-hud p-4 rounded-lg flex flex-col gap-1">
                  <span className="text-xs text-sky-400/70 uppercase">Authorized Operator</span>
                  <span className="text-sm text-cyan-300 font-semibold">{specsModal.operator}</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* MIDDLE SECTION: CORE TELEMETRY (LEFT) & OPTICAL SENSORS (RIGHT) */}
        <div className="flex justify-between items-center w-full px-2 pointer-events-none">
          {/* LEFT CYBER CARD: CORE TELEMETRY & AUDIO BUS */}
          <div className="cyber-card rounded-xl p-3.5 w-60 flex flex-col gap-2.5 pointer-events-auto font-mono">
            <div className="cyber-corner cyber-corner-tl" />
            <div className="cyber-corner cyber-corner-tr" />
            <div className="cyber-corner cyber-corner-bl" />
            <div className="cyber-corner cyber-corner-br" />

            <div className="flex justify-between items-center text-[10px] tracking-widest text-sky-400 font-bold uppercase">
              <span>CORE TELEMETRY</span>
              <span className="text-cyan-300">ONLINE</span>
            </div>

            <div className="flex flex-col gap-1">
              <div className="flex justify-between text-xs text-sky-200">
                <span>CPU LOAD</span>
                <span className="text-cyan-300 font-bold">{telemetry.cpu_percent}%</span>
              </div>
              <div className="w-full bg-sky-950/80 rounded-full h-1.5 overflow-hidden border border-sky-500/30">
                <div
                  className="bg-gradient-to-r from-sky-400 to-cyan-300 h-full rounded-full transition-all duration-500"
                  style={{ width: `${Math.min(100, Math.max(5, telemetry.cpu_percent))}%` }}
                />
              </div>
            </div>

            <div className="flex flex-col gap-1">
              <div className="flex justify-between text-xs text-sky-200">
                <span>RAM USAGE</span>
                <span className="text-purple-300 font-bold">{telemetry.ram_percent}%</span>
              </div>
              <div className="w-full bg-sky-950/80 rounded-full h-1.5 overflow-hidden border border-purple-500/30">
                <div
                  className="bg-gradient-to-r from-purple-400 to-cyan-300 h-full rounded-full transition-all duration-500"
                  style={{ width: `${Math.min(100, Math.max(5, telemetry.ram_percent))}%` }}
                />
              </div>
            </div>

            <div className="flex items-center justify-between pt-1 border-t border-sky-500/20">
              <span className="text-[10px] text-sky-400/80 uppercase">AUDIO BUS</span>
              <div className="flex items-center gap-1 h-5">
                <div className="wave-bar" style={{ animationDelay: "0ms" }} />
                <div className="wave-bar" style={{ animationDelay: "150ms" }} />
                <div className="wave-bar" style={{ animationDelay: "300ms" }} />
                <div className="wave-bar" style={{ animationDelay: "75ms" }} />
                <div className="wave-bar" style={{ animationDelay: "225ms" }} />
              </div>
            </div>
          </div>

          {/* RIGHT CYBER CARD: OPTICAL SENSORS (60 FPS LIVE FEED & DUAL-HAND TRACKING) */}
          <div className="cyber-card rounded-xl p-2.5 w-64 flex flex-col gap-2 pointer-events-auto">
            <div className="cyber-corner cyber-corner-tl" />
            <div className="cyber-corner cyber-corner-tr" />
            <div className="cyber-corner cyber-corner-bl" />
            <div className="cyber-corner cyber-corner-br" />

            <div className="flex justify-between items-center text-[10px] tracking-widest text-sky-400 font-mono font-bold uppercase">
              <span>OPTICAL SENSORS</span>
              <span className="text-emerald-400">60 FPS</span>
            </div>

            <div className="relative w-full h-36 bg-black/90 rounded-lg overflow-hidden border border-sky-500/30 shadow-inner">
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                className="w-full h-full object-cover -scale-x-100 filter brightness-110 contrast-105"
              />
              <canvas
                ref={overlayCanvasRef}
                width={640}
                height={480}
                className="absolute inset-0 w-full h-full pointer-events-none"
              />
              <div className="absolute inset-0 pointer-events-none border border-cyan-400/25 m-1 rounded" />
            </div>

            <div className="flex flex-col gap-1 text-[11px] font-mono">
              <div className="flex justify-between items-center">
                <span className="text-sky-400 font-bold uppercase">Left:</span>
                <span className="text-cyan-300 truncate max-w-[150px]">{leftGesture}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-purple-400 font-bold uppercase">Right:</span>
                <span className="text-purple-300 truncate max-w-[150px]">{rightGesture}</span>
              </div>
            </div>
          </div>
        </div>

        {/* BOTTOM SECTION: APPS, 8 AGENTS, ACTION CHIPS & COMMAND FORM */}
        <footer className="w-full flex flex-col gap-2.5 pb-1">
          {/* BOTTOM CYBER CARD: WINDOWS, ANDROID & 8 SPECIALIST AGENTS */}
          <div className="w-full flex justify-center pointer-events-auto">
            <div className="cyber-card px-5 py-2.5 rounded-xl flex flex-col gap-2 max-w-5xl shadow-[0_0_35px_rgba(0,240,255,0.12)]">
              <div className="cyber-corner cyber-corner-tl" />
              <div className="cyber-corner cyber-corner-tr" />
              <div className="cyber-corner cyber-corner-bl" />
              <div className="cyber-corner cyber-corner-br" />

              {/* WINDOWS ROW */}
              <div className="flex items-center gap-2 flex-wrap justify-center">
                <span className="text-[10px] font-mono font-bold tracking-wider text-sky-400 uppercase mr-1">WINDOWS:</span>
                <button onClick={() => sendCommand("open chrome")} className="hud-btn" disabled={isProcessing}>
                  🌐 Chrome
                </button>
                <button onClick={() => sendCommand("open notepad")} className="hud-btn" disabled={isProcessing}>
                  📝 Notepad
                </button>
                <button onClick={() => sendCommand("open calculator")} className="hud-btn" disabled={isProcessing}>
                  🔢 Calculator
                </button>
                <button onClick={() => sendCommand("open code")} className="hud-btn" disabled={isProcessing}>
                  ⚡ VS Code
                </button>
                <button onClick={() => sendCommand("open explorer")} className="hud-btn" disabled={isProcessing}>
                  📁 Explorer
                </button>
                <button onClick={() => sendCommand("open terminal")} className="hud-btn" disabled={isProcessing}>
                  💻 Terminal
                </button>
                <button onClick={() => sendCommand("screenshot")} className="hud-btn border-cyan-400/50 bg-cyan-950/40" disabled={isProcessing}>
                  📸 Screenshot
                </button>
                <button onClick={() => sendCommand("system status")} className="hud-btn border-sky-400/50 bg-sky-950/40" disabled={isProcessing}>
                  📊 Specs
                </button>
              </div>

              {/* ANDROID ROW */}
              <div className="flex items-center gap-2 flex-wrap justify-center pt-1 border-t border-purple-500/20">
                <span className="text-[10px] font-mono font-bold tracking-wider text-purple-400 uppercase mr-1">ANDROID:</span>
                <button onClick={() => sendCommand("open youtube on phone")} className="hud-btn border-purple-500/40 hover:border-purple-300" disabled={isProcessing}>
                  📱 YouTube
                </button>
                <button onClick={() => sendCommand("open camera on phone")} className="hud-btn border-purple-500/40 hover:border-purple-300" disabled={isProcessing}>
                  📷 Camera
                </button>
                <button onClick={() => sendCommand("open whatsapp on phone")} className="hud-btn border-purple-500/40 hover:border-purple-300" disabled={isProcessing}>
                  💬 WhatsApp
                </button>
                <button onClick={() => sendCommand("phone home")} className="hud-btn border-purple-500/40 hover:border-purple-300" disabled={isProcessing}>
                  🏠 Home
                </button>
                <button onClick={() => sendCommand("phone back")} className="hud-btn border-purple-500/40 hover:border-purple-300" disabled={isProcessing}>
                  ◀ Back
                </button>
              </div>

              {/* 8 SPECIALIST AGENTS ROW */}
              <div className="flex items-center gap-1.5 flex-wrap justify-center pt-1 border-t border-cyan-500/20">
                <span className="text-[10px] font-mono font-bold tracking-wider text-cyan-400 uppercase mr-1">8 AGENTS:</span>
                {SPECIALIST_AGENTS.map((agent) => (
                  <button
                    key={agent.id}
                    onClick={() => {
                      setSelectedAgent(agent.id);
                      sendCommand(`ask ${agent.id}`);
                    }}
                    title={`${agent.name} // ${agent.role} - ${agent.desc}`}
                    className={`agent-chip ${selectedAgent === agent.id ? "agent-chip-active" : ""}`}
                    disabled={isProcessing}
                  >
                    <span>{agent.icon}</span>
                    <span>{agent.name}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* QUICK PROMPT CHIPS */}
          <div className="flex justify-center items-center gap-2 pointer-events-auto flex-wrap">
            <button onClick={() => sendCommand("Open Chrome and play Star Boy in YouTube.")} className="hud-chip">
              ▶ Play Star Boy on YouTube
            </button>
            <button onClick={() => sendCommand("open notepad")} className="hud-chip">
              📝 New Notepad Note
            </button>
            <button onClick={() => sendCommand("screenshot")} className="hud-chip">
              📸 Capture Screenshot
            </button>
            <button onClick={() => sendCommand("system status")} className="hud-chip">
              📊 System Specifications
            </button>
            <button onClick={() => sendCommand("open terminal")} className="hud-chip">
              💻 Launch Terminal
            </button>
            <button onClick={() => sendCommand("what time is it")} className="hud-chip">
              ⏱ Local Time
            </button>
          </div>

          {/* COMMAND INPUT FORM */}
          <div className="w-full flex justify-center pointer-events-auto">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const form = e.currentTarget;
                const input = form.elements.namedItem("cmd") as HTMLInputElement;
                if (input && input.value.trim()) {
                  sendCommand(input.value.trim());
                  input.value = "";
                }
              }}
              className="glass-hud flex gap-3 w-full max-w-3xl px-4 py-2.5 items-center border-cyan-400/40 shadow-[0_0_30px_rgba(0,240,255,0.18)]"
            >
              <div className="flex items-center gap-2 pl-1">
                <div className="w-2.5 h-2.5 rounded-full bg-cyan-400 animate-ping" />
                <span className="text-cyan-400 font-bold text-xs tracking-wider font-mono">FRIDAY //</span>
              </div>
              <input
                type="text"
                name="cmd"
                value={voiceTranscript || undefined}
                onChange={(e) => setVoiceTranscript(e.target.value)}
                placeholder="Give any command or speak to FRIDAY (e.g. 'Open Chrome and play Star Boy in YouTube', 'open notepad', 'screenshot')..."
                className="flex-1 bg-transparent text-sky-100 text-sm outline-none px-2 placeholder-sky-400/40 font-medium"
                autoComplete="off"
              />
              <button
                type="button"
                onClick={toggleListening}
                className={`p-2 rounded-lg border transition ${
                  isListening
                    ? "bg-red-950/90 border-red-500 text-red-300 animate-pulse shadow-[0_0_15px_rgba(239,68,68,0.6)]"
                    : "bg-cyan-950/50 border-cyan-500/30 text-cyan-300 hover:border-cyan-400 hover:text-white"
                }`}
                title={isListening ? "Stop Voice Listening" : "Speak to FRIDAY"}
              >
                {isListening ? "🔴" : "🎤"}
              </button>
              <button
                type="submit"
                disabled={isProcessing}
                className="hud-btn bg-cyan-950/90 hover:bg-cyan-800 text-cyan-200 text-xs px-6 py-2 font-bold uppercase tracking-wider transition shadow-[0_0_15px_rgba(0,240,255,0.3)] disabled:opacity-50"
              >
                {isProcessing ? "PROCESSING..." : "EXECUTE"}
              </button>
            </form>
          </div>
        </footer>
      </div>
    </main>
  );
}
