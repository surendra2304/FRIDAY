"use client";

import { useState, useEffect, useRef } from "react";
import {
  Activity, BarChart3, Brain, Camera,
  Code2, Cpu, ExternalLink, Globe,
  HardDrive, Maximize2, Mic, MicOff,
  Minimize2, Orbit, Search, Send,
  ShieldCheck, Sparkles, Terminal, TrendingUp, User, Video, VideoOff,
  Volume2, VolumeX, Wifi, X, Zap,
} from "lucide-react";
import * as THREE from "three";
import { FilesetResolver, HandLandmarker } from "@mediapipe/tasks-vision";

const WASM_URL = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.0.1/wasm";
const HAND_MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";

export interface SpecialistAgent {
  id: string;
  name: string;
  role: string;
  tagline?: string;
  category: "Intelligence" | "Cognition" | "Execution" | "Defense";
  endpoint: string;
  icon: any;
  accent: string;
  glow?: string;
  status: "ONLINE" | "DEGRADED" | "STANDBY" | "BUSY";
  latencyMs: number;
  model: string;
  host?: string;
  description: string;
  capabilities: string[];
}

interface Pt {
  x: number;
  y: number;
}

function dist(a: Pt, b: Pt): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function classifyHand(lm: any[]): { gesture: string; color: string; pinch: number } {
  const palm: Pt = {
    x: (lm[0].x + lm[5].x + lm[9].x + lm[13].x + lm[17].x) / 5,
    y: (lm[0].y + lm[5].y + lm[9].y + lm[13].y + lm[17].y) / 5,
  };
  const handSize: number = Math.max(dist(lm[0], lm[9]), 0.22);
  const tipIds: number[] = [4, 8, 12, 16, 20];
  const tips: Pt[] = tipIds.map((i: number) => lm[i] as Pt);
  const pinch: number = Math.min(1, dist(lm[4], lm[8]) / handSize);
  const tipD: number[] = tips.map((t: Pt) => dist(t, palm) / handSize);
  const open: boolean =
    tipD[0] > 0.55 &&
    tipD[1] > 0.55 &&
    tipD[2] > 0.55 &&
    tipD[3] > 0.45 &&
    tipD[4] > 0.35;
  const fist: boolean = tipD.every((d: number) => d < 0.36);
  const point: boolean =
    tipD[1] > 0.55 &&
    tipD[2] < 0.3 &&
    tipD[3] < 0.28 &&
    tipD[4] < 0.28 &&
    tipD[0] < 0.4;
  const peace: boolean =
    tipD[1] > 0.5 &&
    tipD[2] > 0.5 &&
    tipD[3] < 0.3 &&
    tipD[4] < 0.3 &&
    tipD[0] < 0.4;
  const pinchOn: boolean = pinch < 0.3 && tipD[1] > 0.45;
  let gesture: string = "TRACKING";
  let color: string = "#00f0ff";
  if (pinchOn) {
    gesture = "PINCH";
    color = "#f59e0b";
  } else if (fist) {
    gesture = "FIST";
    color = "#a855f7";
  } else if (point) {
    gesture = "POINT";
    color = "#00f0ff";
  } else if (peace) {
    gesture = "PEACE";
    color = "#10b981";
  } else if (open) {
    gesture = "OPEN";
    color = "#38bdf8";
  }
  return { gesture, color, pinch };
}
const HAND_CONNECTIONS: number[][] = [
  [0, 1],
  [1, 2],
  [2, 3],
  [3, 4],
  [0, 5],
  [5, 6],
  [6, 7],
  [7, 8],
  [5, 9],
  [9, 10],
  [10, 11],
  [11, 12],
  [9, 13],
  [13, 14],
  [14, 15],
  [15, 16],
  [13, 17],
  [17, 18],
  [18, 19],
  [19, 20],
  [0, 17],
  [17, 20],
];

const GESTURE_LEGEND: Array<{ name: string; hint: string; color: string }> = [
  { name: "OPEN", hint: "Brighten core", color: "#38bdf8" },
  { name: "POINT", hint: "Steer & aim", color: "#00f0ff" },
  { name: "PINCH", hint: "Focus orb", color: "#f59e0b" },
  { name: "FIST", hint: "Boost spin", color: "#a855f7" },
  { name: "PEACE", hint: "Calm hold", color: "#10b981" },
];
const CANONICAL_FLEET: SpecialistAgent[] = [
  {
    id: "intelx",
    name: "INTELX",
    role: "Macro Research & Evidence Intelligence",
    category: "Intelligence",
    endpoint: "https://intelx-3cz1.onrender.com",
    icon: Search,
    accent: "#8b5cf6",
    status: "ONLINE",
    latencyMs: 38,
    model: "DeepSeek R1 // Evidence Graph Synthesizer",
    description: "Autonomous evidence crawling, contradiction resolution,and macroeconomic research with citation-anchored synthesis.",
    capabilities: ["Evidence Extraction", "Contradiction Detection", "Macro Research"],
  },
{
    id: "futuris",
    name: "FUTURIS",
    role: "Calibrated Probabilistic Forecasting",
    category: "Intelligence",
    endpoint: "https://futuris-x4f4.onrender.com",
    icon: TrendingUp,
    accent: "#06b6d4",
    status: "ONLINE",
    latencyMs: 42,
    model: "Calibrated Bayesian // Probabilistic Engine",
    description: "Calibrated predictive modeling and horizon forecasting with Brier scores and ECE across multi-target distributions.",
    capabilities: ["Confidence Calibration", "Horizon Forecasting", "Brier Evaluation"],
  },
{
    id: "memora",
    name: "MEMORA",
    role: "Persistent Vector Memory Fabric",
    category: "Cognition",
    endpoint: "https://memora-9zr9.onrender.com",
    icon: Brain,
    accent: "#38bdf8",
    status: "ONLINE",
    latencyMs: 14,
    model: "VectorDB // 9GB Turso AWS Mumbai",
    description: "Persistent cloud vector memory with episodic recall, operator profile indexing,and cross-agent knowledge sync.",
    capabilities: ["Semantic Search", "Episodic Recall", "Profile Indexing"],
  },
{
    id: "forge",
    name: "FORGE",
    role: "Mission-Critical System Execution",
    category: "Execution",
    endpoint: "http://127.0.0.1:8002",
    icon: Code2,
    accent: "#3b82f6",
    status: "DEGRADED",
    latencyMs: 0,
    model: "Swarm Maker // Local DevOps Execution",
    description: "Local daemon microservice for orchestrated production execution, deployments,and critical-worker spawning.",
    capabilities: ["Critical Worker Spawn", "Deployment", "Risk Controls"],
  },
{
    id: "cortex",
    name: "CORTEX",
    role: "Automated System Orchestration",
    category: "Execution",
    endpoint: "http://127.0.0.1:9001",
    icon: Globe,
    accent: "#f59e0b",
    status: "DEGRADED",
    latencyMs: 0,
    model: "Semantic Router // System Automation Controller",
    description: "Automated system orchestration, browser automation, and semantic navigation across local services.",
    capabilities: ["System Orchestration", "Browser Automation", "Service Routing"],
  },
{
    id: "sentinel",
    name: "SENTINEL",
    role: "Security Guard & Real-Time Defense",
    category: "Defense",
    endpoint: "http://127.0.0.1:8003",
    icon: ShieldCheck,
    accent: "#10b981",
    status: "DEGRADED",
    latencyMs: 0,
    model: "Gradient Boosting // Intrusion & Anomaly Defense",
    description: "Anomaly detection, session safeguards,and ingress traffic intrusion monitoring across the local perimeter.",
    capabilities: ["Intrusion Detection", "Session Safeguards", "Anomaly Alerts"],
  },
{
    id: "stratex",
    name: "STRATEX",
    role: "Strategy, Research & Market Insight",
    category: "Execution",
    endpoint: "https://stratex-3xnd.onrender.com",
    icon: BarChart3,
    accent: "#14b8a6",
    status: "ONLINE",
    latencyMs: 31,
    model: "Strategic Planner // Falcon Series",
    description: "Deceptive-measure analysis, market insight,and autonomous strategic planning synthesized into executive briefs.",
    capabilities: ["Strategy Planning", "Market Insight", "Brief Synthesis"],
  },
{
    id: "inference",
    name: "INFERENCE",
    role: "Edge Inference & Rapid Command",
    category: "Cognition",
    endpoint: "https://inference-46pq.onrender.com",
    icon: Zap,
    accent: "#ec4899",
    status: "ONLINE",
    latencyMs: 25,
    model: "Meta-Llama // Edge Inference Engine",
    description: "Lightweight edge inference for rapid commands, streaming predictions,and local low-latency cognitive tasks.",
    capabilities: ["Edge Inference", "Rapid Commands", "Low Latency"],
  },
];

// Deploy-time status merge \u2014 live ping data overrides the canonical snapshot.
export default function FridaySovereignCore() {
  const [coreState, setCoreState] = useState<
    "standby" | "listening" | "thinking" | "speaking"
  >("standby");
  const [promptInput, setPromptInput] = useState("");
  const [chatLog, setChatLog] = useState<
    { role: "user" | "friday"; text: string }[]
  >([
    { role: "friday", text: "At your service, Surendra. Core systems nominal \u2014 how shall I assist?" },
  ]);
  const [lastSpeech, setLastSpeech] = useState(
    "Standing by for your directive."
  );
  const [audioFeedback, setAudioFeedback] = useState(true);
  const [isListening, setIsListening] = useState(false);
  const [telemetry, setTelemetry] = useState({
    cpu: 24,
    ram: 46,
    storage: 61,
    network: 128,
  });
  const [proactiveAnnouncement, setProactiveAnnouncement] = useState<
    string | null
  >(null);
  const [liveAgents, setLiveAgents] = useState<SpecialistAgent[]>(
    CANONICAL_FLEET
  );
  const [currentTime, setCurrentTime] = useState("05:30 PM");
  const [currentDate, setCurrentDate] = useState("Mon, Sep 7, 2026");
  const [isCameraActive, setIsCameraActive] = useState(true);
const [isFullscreen, setIsFullscreen] = useState(false);
  const [handState, setHandState] = useState({
    present: false,
    gesture: "none",
    color: "#00f0ff",
    pinch: 1,
  });
  const [handModelReady, setHandModelReady] = useState(false);
  const [handError, setHandError] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<SpecialistAgent | null>(
    null
  );
  const [agentDirectiveInput, setAgentDirectiveInput] = useState("");
  const [agentDirectiveResponse, setAgentDirectiveResponse] = useState<
    string | null
  >(null);
  const [isAgentExecuting, setIsAgentExecuting] = useState(false);
  const [screenshotData, setScreenshotData] = useState<string | null>(null);
  const [showScreenshot, setShowScreenshot] = useState(false);
  const [showDispatch, setShowDispatch] = useState(false);
  const [isOnline, setIsOnline] = useState(true);
  const gestureName: string | null = handState.present ? handState.gesture : null;

  const videoRef = useRef<HTMLVideoElement>(null);
  const camBoxRef = useRef<HTMLDivElement>(null);
  const camCanvasRef = useRef<HTMLCanvasElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const recognitionRef = useRef<any>(null);
  const gestureRef = useRef({
    present: false,
    gesture: "none",
    color: "#00f0ff",
    x: 0.5,
    y: 0.5,
    pinch: 1,
  });
  const lastUiRef = useRef(0);
  const chatEndRef = useRef<HTMLDivElement>(null);
useEffect(() => {
  const tick = () => {
    const d = new Date();
    setCurrentTime(
      d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: true })
    );
    setCurrentDate(
      d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" })
    );
  };
  tick();
  const timer = setInterval(tick, 1000);
  return () => clearInterval(timer);
}, []);

useEffect(() => {
  let alive = true;
  const poll = async () => {
    try {
      const [telRes, agentsRes] = await Promise.all([
        fetch("http://127.0.0.1:8001/api/telemetry"),
        fetch("http://127.0.0.1:8001/api/agents/status"),
      ]);
      if (telRes.ok) {
        const data = await telRes.json();
        if (data && typeof data.cpu === "number") {
          setTelemetry({
            cpu: data.cpu,
            ram: data.ram ?? 46,
            storage: data.storage ?? 61,
            network: data.network ?? 128,
          });
        }
      }
      if (agentsRes.ok) {
        const data = await agentsRes.json();
        const list: SpecialistAgent[] = Array.isArray(data)
          ? data
          : Array.isArray((data as any)?.agents)
            ? (data as any).agents
            : data?.fleet ?? [];
        if (list.length) {
          setLiveAgents((prev) =>
            list.map((a: any) => {
              const known = prev.find((p) => p.id === a.id);
              return {
                ...known,
                ...a,
                id: a.id,
                name: a.name ?? known?.name ?? a.id.toUpperCase(),
                endpoint: a.endpoint ?? known?.endpoint ?? "",
                accent: a.accent ?? known?.accent ?? "#00f0ff",
                status: String(a.status ?? "STANDBY").toUpperCase(),
                latencyMs: typeof a.latency_ms === "number"
                  ? a.latency_ms
                  : typeof a.latencyMs === "number"
                  ? a.latencyMs
                  : known?.latencyMs ?? 0,
              };
            })
          );
        }
      }
    } catch { /* backend offline \u2014 keep last snapshot */ }
  };
  poll();
  const timer = setInterval(poll, 4000);
  return () => { alive = false; clearInterval(timer); };
}, []);
useEffect(() => {
  let alive = true;
  const pollProactive = async () => {
    try {
      const res = await fetch("http://127.0.0.1:8001/api/proactive");
      if (!res.ok) return;
      const data = await res.json();
      if (!alive) return;
      if (data && data.message && data.message.trim()) {
        setProactiveAnnouncement(data.message.trim());
        if (audioFeedback) {
          try {
            const u = new SpeechSynthesisUtterance(data.message.trim());
            u.rate = 1;
            window.speechSynthesis.speak(u);
          } catch { /* no audio \u2014 silent */ }
        }
      }
    } catch { /* backend offline */ }
  };
  pollProactive();
  const timer = setInterval(pollProactive, 20000);
  return () => { alive = false; clearInterval(timer); };
}, [audioFeedback]);

useEffect(() => {
  chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
}, [chatLog]);

useEffect(() => {
  const handler = () => {
    setIsFullscreen(!!document.fullscreenElement);
  };
  document.addEventListener("fullscreenchange", handler);
  return () => document.removeEventListener("fullscreenchange", handler);
}, []);
useEffect(() => {
  if (!isCameraActive) return;
  let stream: MediaStream | null = null;
  let landmarker: HandLandmarker | null = null;
  let raf = 0;
  let lastVideoTime = -1;

  const startCam = async () => {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
        audio: false,
      });
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.onloadedmetadata = () => {
          const v = videoRef.current;
          const box = camBoxRef.current;
          const cv = camCanvasRef.current;
          if (!v || !box || !cv) return;
          box.style.aspectRatio = `${v.videoWidth} / ${v.videoHeight}`;
          cv.width = v.videoWidth;
          cv.height = v.videoHeight;
        };
      }
    } catch { /* camera denied \u2014 UI shows fallback frame */ }
  };

  const initHandModel = async () => {
    try {
      const vision = await FilesetResolver.forVisionTasks(WASM_URL);
      landmarker = await HandLandmarker.createFromOptions(vision, {
        baseOptions: { modelAssetPath: HAND_MODEL_URL, delegate: "GPU" },
        runningMode: "VIDEO",
        numHands: 2,
      });
      setHandModelReady(true);
    } catch (e) {
      setHandError(e instanceof Error ? e.message : "Hand model unavailable");
    }
  };

  startCam();
  initHandModel();
const detectLoop = () => {
    raf = requestAnimationFrame(detectLoop);
    const v = videoRef.current;
    const cv = camCanvasRef.current;
    if (!isCameraActive || !landmarker || !v || !cv) return;
    if (v.readyState < 2 || !v.videoWidth) return;
    // Skip if video time hasn't changed (prevents duplicate detections)
    if (v.currentTime === lastVideoTime) return;
    lastVideoTime = v.currentTime;
    let results;
    try {
      results = landmarker.detectForVideo(v, performance.now());
    } catch { return; }
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, cv.width, cv.height);
if (results.landmarks && results.landmarks.length > 0) {
      // Track all detected hands
      const hands = results.landmarks;
      const handedness = results.handedness || [];
      // Use the first hand for gesture control (or the right hand if available)
      let primaryIdx = 0;
      if (handedness.length > 1) {
        const rightIdx = handedness.findIndex((h: any) => h[0]?.categoryName === "Right");
        if (rightIdx >= 0) primaryIdx = rightIdx;
      }
      const lm: any = hands[primaryIdx];
      const cls = classifyHand(lm);
      const cw: number = cv.width;
      const ch: number = cv.height;

      // Draw all hands
      for (let h = 0; h < hands.length; h++) {
        const handLm = hands[h];
        const hCls = h === primaryIdx ? cls : classifyHand(handLm);

        // Draw skeleton connections with glow effect
        ctx.shadowBlur = 8;
        ctx.shadowColor = hCls.color;
        ctx.strokeStyle = hCls.color;
        ctx.lineWidth = Math.max(2, cw * 0.005);
        ctx.globalAlpha = 0.95;
        for (const pair of HAND_CONNECTIONS) {
          const a = handLm[pair[0]];
          const b = handLm[pair[1]];
          if (!a || !b) continue;
          ctx.beginPath();
          ctx.moveTo(a.x * cw, a.y * ch);
          ctx.lineTo(b.x * cw, b.y * ch);
          ctx.stroke();
        }

        // Draw landmark points
        ctx.shadowBlur = 0;
        ctx.globalAlpha = 1;
        const tips = [4, 8, 12, 16, 20];
        handLm.forEach((p: any, i: number) => {
          if (!p) return;
          // Outer glow for fingertips
          if (tips.includes(i)) {
            ctx.beginPath();
            ctx.arc(p.x * cw, p.y * ch, cw * 0.025, 0, Math.PI * 2);
            ctx.fillStyle = hCls.color + "40";
            ctx.fill();
          }
          // Main point
          ctx.beginPath();
          ctx.arc(p.x * cw, p.y * ch, tips.includes(i) ? cw * 0.018 : cw * 0.01, 0, Math.PI * 2);
          ctx.fillStyle = tips.includes(i) ? "#ffffff" : hCls.color;
          ctx.fill();
        });
      }

      // Calculate palm center for orb control
      const palmX = (lm[0].x + lm[5].x + lm[9].x + lm[13].x + lm[17].x) / 5;
      const palmY = (lm[0].y + lm[5].y + lm[9].y + lm[13].y + lm[17].y) / 5;

      gestureRef.current = {
        present: true,
        gesture: cls.gesture,
        color: cls.color,
        x: palmX,
        y: palmY,
        pinch: cls.pinch,
      };
      const now = performance.now();
      if (now - lastUiRef.current > 100) {
        lastUiRef.current = now;
        setHandState({ present: true, gesture: cls.gesture, color: cls.color, pinch: cls.pinch });
      }
    } else {
      const now = performance.now();
      if (now - lastUiRef.current > 200) {
        lastUiRef.current = now;
        gestureRef.current = { ...gestureRef.current, present: false, gesture: "none" };
        setHandState((s) => ({ ...s, present: false, gesture: "none" }));
      }
    }
  };
  raf = requestAnimationFrame(detectLoop);

  return () => {
    cancelAnimationFrame(raf);
    if (stream) stream.getTracks().forEach((t) => t.stop());
    if (landmarker) {
      try { landmarker.close(); } catch { /* ignore */ }
    }
  };
}, [isCameraActive]);
useEffect(() => {
  const canvas = canvasRef.current;
  if (!canvas) return;
  const width = canvas.clientWidth || 420;
  const height = canvas.clientHeight || 380;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
  camera.position.z = 7;
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(width, height);
    // A. Central Glowing Core Sphere (Clean, Pure Arc Reactor Energy)
    const coreGeo = new THREE.SphereGeometry(1.35, 48, 48);
    const coreMat = new THREE.MeshBasicMaterial({
      color: 0x00f0ff,
      wireframe: true,
      transparent: true,
      opacity: 0.35,
    });
    const coreMesh = new THREE.Mesh(coreGeo, coreMat);
    scene.add(coreMesh);

    // Inner Radiant Nucleus
    const nucleusGeo = new THREE.SphereGeometry(0.75, 32, 32);
    const nucleusMat = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.85,
    });
    const nucleusMesh = new THREE.Mesh(nucleusGeo, nucleusMat);
    scene.add(nucleusMesh);
    const particleCount = 280;
    const particleGeo = new THREE.BufferGeometry();
    const positions = new Float32Array(particleCount * 3);
    for (let i = 0; i < particleCount; i++) {
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(Math.random() * 2 - 1);
      const r = 2.1 + Math.random() * 0.9;
      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = r * Math.cos(phi);
    }
    particleGeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    const particleMat = new THREE.PointsMaterial({
      color: 0x38bdf8,
      size: 0.055,
      transparent: true,
      opacity: 0.75,
      blending: THREE.AdditiveBlending,
    });
    const particleSystem = new THREE.Points(particleGeo, particleMat);
    scene.add(particleSystem);
    const ringGeo = new THREE.RingGeometry(2.3, 2.38, 64);
    const ringMat = new THREE.MeshBasicMaterial({
      color: 0x00f0ff,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.45,
    });
    const horizonRing = new THREE.Mesh(ringGeo, ringMat);
    horizonRing.rotation.x = Math.PI / 2.3;
    scene.add(horizonRing);
    let animId: number;
    let clock = new THREE.Clock();

    const renderLoop = () => {
      animId = requestAnimationFrame(renderLoop);
      const elapsedTime = clock.getElapsedTime();

      // Dynamic rotation responsive to coreState
      const rotSpeed =
        coreState === "thinking"
          ? 0.022
          : coreState === "speaking"
          ? 0.016
          : coreState === "listening"
          ? 0.012
          : 0.005;

      coreMesh.rotation.y += rotSpeed;
      coreMesh.rotation.x += rotSpeed * 0.3;
      particleSystem.rotation.y -= rotSpeed * 0.4;
      horizonRing.rotation.z += rotSpeed * 0.5;

      // Harmonic breathing expansion
      const pulseMultiplier = coreState === "speaking" ? 0.08 : 0.035;
      const scale = 1 + Math.sin(elapsedTime * 3.0) * pulseMultiplier;
      coreMesh.scale.set(scale, scale, scale);

      // Color reactivity
      if (coreState === "listening") {
        coreMat.color.setHex(0x10b981); // Emerald
        particleMat.color.setHex(0x34d399);
      } else if (coreState === "thinking") {
        coreMat.color.setHex(0xa855f7); // Violet
        particleMat.color.setHex(0xc084fc);
      } else if (coreState === "speaking") {
        coreMat.color.setHex(0x38bdf8); // Brilliant Cyan
        particleMat.color.setHex(0x00f0ff);
      } else {
        coreMat.color.setHex(0x00f0ff); // Normal Electric Cyan
        particleMat.color.setHex(0x38bdf8);
      }

      // H. Hand-gesture steering (MediaPipe palm drives the core)
      const hG2 = gestureRef.current;
      const hStep1 =
        hG2.gesture === "FIST"
          ? 0.02
          : hG2.gesture === "POINT"
          ? 0.012
          : hG2.gesture === "OPEN"
          ? 0.006
          : 0;
      coreMesh.rotation.y += hG2.present ? hStep1 : 0;
      coreMesh.rotation.x += hG2.present
        ? Math.sin(elapsedTime * 0.6) * 0.2 + (hG2.y - 0.5) * 1.2
        : 0;
      particleSystem.rotation.y -= hStep1 * 0.4;

      horizonRing.rotation.z += hStep1 * 0.5;
      const hScale2 =
        hG2.gesture === "PINCH"
          ? -0.15
          : hG2.gesture === "OPEN"
          ? 0.06
          : hG2.gesture === "FIST"
          ? Math.sin(elapsedTime * 6) * 0.04
          : 0;
      coreMesh.scale.set(scale + hScale2, scale + hScale2, scale + hScale2);
      if (hG2.gesture === "POINT") {
        (ringMat as THREE.MeshBasicMaterial).opacity = 0.6;
      } else if (hG2.present) {
        (ringMat as THREE.MeshBasicMaterial).opacity = 0.4;
      } else {
        (ringMat as THREE.MeshBasicMaterial).opacity = 0.3;
      }

      renderer.render(scene, camera);
    };

    renderLoop();

    const handleResize = () => {
      if (!canvas) return;
      camera.aspect = canvas.clientWidth / canvas.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(canvas.clientWidth, canvas.clientHeight);
    };

    window.addEventListener("resize", handleResize);
    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener("resize", handleResize);
      renderer.dispose();
      coreGeo.dispose();
      coreMat.dispose();
      nucleusGeo.dispose();
      nucleusMat.dispose();
      particleGeo.dispose();
      particleMat.dispose();
      ringGeo.dispose();
      ringMat.dispose();
    };
  }, [coreState]);
const playSFX = (kind: "click" | "chirp" | "engage") => {
    if (!audioFeedback) return;
    try {
      const ctx = new AudioContext();
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      const freq = kind === "click" ? 660 : kind === "chirp" ? 990 :  440;
      o.type = "sine";
      o.frequency.value = freq;
      g.gain.value = kind === "engage" ? 0.08 : 0.05;
      o.connect(g);
      g.connect(ctx.destination);
      o.start();
      o.stop(ctx.currentTime + 0.12);
      o.onended = () => ctx.close();
    } catch { /* audio unavailable */ }
  };

  const femaleVoiceRef = useRef<SpeechSynthesisVoice | null>(null);
  const manuallyStoppedRef = useRef(false);

  // Load female voice
  useEffect(() => {
    const loadVoice = () => {
      const voices = window.speechSynthesis.getVoices();
      const female =
        voices.find(v => v.name.toLowerCase().includes("female")) ||
        voices.find(v => v.name.toLowerCase().includes("zira")) ||
        voices.find(v => v.name.toLowerCase().includes("samantha")) ||
        voices.find(v => v.name.toLowerCase().includes("victoria")) ||
        voices.find(v => v.name.toLowerCase().includes("karen")) ||
        voices.find(v => v.name.toLowerCase().includes("moira")) ||
        voices.find(v => v.name.toLowerCase().includes("tessa")) ||
        voices.find(v => v.name.toLowerCase().includes("fiona")) ||
        voices.find(v => v.name.toLowerCase().includes("google uk english female")) ||
        voices.find(v => v.name.toLowerCase().includes("google us english")) ||
        voices.find(v => v.lang.startsWith("en") && v.name.toLowerCase().includes("woman")) ||
        voices.find(v => v.lang.startsWith("en")) ||
        null;
      femaleVoiceRef.current = female;
    };
    loadVoice();
    window.speechSynthesis.onvoiceschanged = loadVoice;
    return () => { window.speechSynthesis.onvoiceschanged = null; };
  }, []);

  const speakFriday = (text: string) => {
    if (!audioFeedback || !text) return;
    setCoreState("speaking");
    try {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 1.05;
      u.pitch = 1.35;
      if (femaleVoiceRef.current) u.voice = femaleVoiceRef.current;
      u.onend = () => setCoreState("standby");
      u.onerror = () => setCoreState("standby");
      window.speechSynthesis.speak(u);
    } catch { setCoreState("standby"); }
  };
const toggleSpeechRecognition = () => {
    const w: any = window as any;
    const SR = w.SpeechRecognition || w.webkitSpeechRecognition;
    if (!SR) {
      setLastSpeech("Voice input not supported in this browser.");
      return;
    }
    if (isListening) {
      manuallyStoppedRef.current = true;
      recognitionRef.current?.stop();
      setIsListening(false);
      setCoreState("standby");
      return;
    }
    manuallyStoppedRef.current = false;
    const rec = new SR();
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.onstart = () => {
      setIsListening(true);
      setCoreState("listening");
    };
    rec.onresult = (event: any) => {
      const txt = event.results[0]?.[0]?.transcript || "";
      if (txt) {
        setPromptInput(txt);
        handleExecuteCommand(txt);
      }
    };
    rec.onend = () => {
      setIsListening(false);
      setCoreState("standby");
      if (!manuallyStoppedRef.current) {
        setTimeout(() => {
          if (!manuallyStoppedRef.current && isListening) return;
          if (!isListening) toggleSpeechRecognition();
        }, 300);
      }
    };
    rec.onerror = () => { setIsListening(false); setCoreState("standby"); };
    recognitionRef.current = rec;
    rec.start();
  };
const handleExecuteCommand = async (custom?: string) => {
    const text = (custom || promptInput).trim();
    if (!text) return;
    playSFX("engage");
    setCoreState("thinking");
    setPromptInput("");
    setChatLog((p) => [...p, { role: "user", text }]);
    try {
      const res = await fetch("http://127.0.0.1:8001/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      const data = await res.json();
      const reply: string = data?.reply || `Directive executed: ${text}`;
      setChatLog((p) => [...p, { role: "friday", text: reply }]);
      setLastSpeech(reply);
      speakFriday(reply);
    } catch {
      const fallback = `Receiving directive "${text}" — the core is online.`;
      setChatLog((p) => [...p, { role: "friday", text: fallback }]);
      setLastSpeech(fallback);
      speakFriday(fallback);
    }
  };
const handleDispatchToAgent = async (agent: SpecialistAgent) => {
    if (!agentDirectiveInput.trim()) return;
    playSFX("engage");
    setIsAgentExecuting(true);
    setAgentDirectiveResponse(null);
    try {
      const res = await fetch("http://127.0.0.1:8001/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: `ask ${agent.id} ${agentDirectiveInput}` }),
      });
      const data = await res.json();
      setAgentDirectiveResponse(data?.reply || "Agent acknowledged.");
    } catch {
      setAgentDirectiveResponse("Endpoint unreachable — agent is offline.");
    }
    setIsAgentExecuting(false);
  };

  const handleCaptureScreenshot = async () => {
    playSFX("chirp");
    try {
      const res = await fetch("http://127.0.0.1:8001/api/screenshot");
      const data = await res.json();
      if (data?.metadata?.image_b64) {
        setScreenshotData(data.metadata.image_b64);
        setShowScreenshot(true);
      }
    } catch { /* no snapshot available */ }
  };

  const toggleFullscreen = () => {
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    } else {
      document.documentElement.requestFullscreen().catch(() => {});
    }
  };

  const onlineCount: number = liveAgents.filter((a) => a.status === "ONLINE").length;
return (
    <main className="relative w-screen h-screen max-h-screen overflow-hidden bg-[#030712] text-slate-100 select-none flex flex-col">
      {/* Background layers */}
      <div className="absolute inset-0 z-0 pointer-events-none">
        <div className="absolute inset-0" style={{ background: "radial-gradient(ellipse at 50% -10%, rgba(8,47,73,0.6), transparent 60%)" }} />
        <div className="absolute inset-0" style={{ background: "radial-gradient(ellipse at 90% 110%, rgba(56,189,248,0.14), transparent 55%)" }} />
        <div className="absolute inset-0 opacity-40" style={{ backgroundImage: "linear-gradient(rgba(56,189,248,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(56,189,248,0.06) 1px, transparent 1px)", backgroundSize: "48px 48px" }} />
        <div className="absolute inset-0" style={{ background: "linear-gradient(to bottom, rgba(3,7,18,0.8), transparent, rgba(2,5,16,0.9))" }} />
      </div>
{/* Header — fleet status lights */}
      <header className="relative z-20 flex items-center justify-between px-4 py-3 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-[#38bdf8] to-[#0ea5e9] shadow-[0_0_18px_rgba(56,189,248,0.45)] flex items-center justify-center font-black text-slate-950">F</div>
          <div>
            <div className="text-sm font-bold tracking-[0.25em] text-sky-300">FRIDAY</div>
            <div className="text-[10px] uppercase tracking-wide text-slate-500">Neural Command Interface</div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowDispatch(true)}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900/70 border border-slate-700/60 hover:border-sky-500/60 hover:shadow-[0_0_14px_rgba(56,189,248,0.25)] transition-all text-xs font-medium"
            title="Dispatch agents"
          >
            {liveAgents.map((a) => (
              <span
                key={a.id}
                className={`w-2.5 h-2.5 rounded-full ${
                  a.status === "ONLINE" ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]" : a.status === "BUSY" ? "bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.8)]" : "bg-slate-600"
                }`}
              />
            ))}
            <span className="text-slate-400 hidden sm:inline">{onlineCount} online</span>
          </button>
          <button
            onClick={toggleFullscreen}
            className="px-3 py-1.5 rounded-lg bg-slate-900/70 border border-slate-700/60 hover:border-sky-500/60 transition-all text-xs text-slate-300"
          >
            ⛶
          </button>
        </div>
      </header>
{/* Main stage — orb */}
      <div className="relative z-10 flex-1 flex min-h-0 gap-4 px-4 pb-2">
        {/* Camera + Hand Tracking Panel */}
        <aside className="hidden lg:flex flex-col gap-3 w-72 shrink-0">
          <div ref={camBoxRef} className="relative rounded-2xl overflow-hidden border border-slate-700/60 bg-slate-900/60 aspect-[4/3]">
            <video ref={videoRef} autoPlay playsInline muted className="absolute inset-0 w-full h-full object-cover scale-x-[-1]" />
            <canvas ref={camCanvasRef} className="absolute inset-0 w-full h-full scale-x-[-1]" />
            {!isCameraActive && (<div className="absolute inset-0 flex items-center justify-center bg-slate-900/80 text-xs text-slate-500">Camera off</div>)}
            {handError && (<div className="absolute bottom-0 left-0 right-0 bg-rose-500/20 text-rose-300 text-[10px] p-1.5 text-center">{handError}</div>)}
          </div>
          <div className="rounded-xl bg-slate-900/60 border border-slate-700/40 p-3">
            <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">Gesture Control</div>
            <div className="space-y-1.5">
              {GESTURE_LEGEND.map((g) => (
                <div key={g.name} className="flex items-center gap-2 text-[11px]">
                  <span className="w-2 h-2 rounded-full" style={{ background: g.color }} />
                  <span className="font-mono font-bold text-slate-300">{g.name}</span>
                  <span className="text-slate-500"> - {g.hint}</span>
                </div>
              ))}
            </div>
            <div className="mt-2 pt-2 border-t border-slate-800 text-[10px] text-slate-500">Model: {handModelReady ? <span className="text-emerald-400">Ready</span> : <span className="text-amber-400">Loading...</span>}</div>
          </div>
        </aside>
        {/* Main stage - orb */}
        <section className="flex-1 flex flex-col items-center justify-center gap-5 min-h-0 pointer-events-none">
        <div className="relative w-full max-w-[560px] aspect-square flex items-center justify-center">
          <canvas ref={canvasRef} className="w-full h-full" />
        </div>
        <div className="pointer-events-auto flex flex-col items-center gap-3">
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.3em] text-slate-400">
            <span className={`w-2 h-2 rounded-full ${isOnline ? "bg-emerald-400 animate-pulse" : "bg-rose-500"}`} />
            {isOnline ? "Core Online" : "Core Offline"}
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-500 max-w-sm text-center leading-relaxed">
            {lastSpeech || "Voice and gesture ready. Ask FRIDAY anything."}
          </div>
          {gestureName && (
            <div className="px-3 py-1 rounded-full bg-sky-500/10 border border-sky-500/30 text-[11px] text-sky-300">
              Gesture: {gestureName}
            </div>
          )}
        </div>
      </section>
      </div>

      {/* Command bar */}
      <div className="relative z-20 px-4 pb-3 shrink-0">
        <div className="flex w-full max-w-2xl mx-auto items-center gap-2 rounded-2xl bg-slate-900/80 border border-slate-700/60 p-2 shadow-[0_0_28px_rgba(56,189,248,0.12)] backdrop-blur">
          <button
            onClick={toggleSpeechRecognition}
            className={`shrink-0 w-10 h-10 rounded-xl flex items-center justify-center text-lg transition-all ${
              isListening ? "bg-rose-500/20 text-rose-300 border border-rose-500/50 animate-pulse" : "bg-sky-500/10 text-sky-300 border border-sky-500/30 hover:bg-sky-500/20"
            }`}
            title="Toggle voice input"
          >
            🎙
          </button>
          <input
            value={promptInput}
            onChange={(e) => setPromptInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleExecuteCommand(); }}
            placeholder="Directive for FRIDAY…"
            className="flex-1 bg-transparent outline-none text-sm placeholder:text-slate-600 text-slate-100"
          />
          <button
            onClick={handleCaptureScreenshot}
            className="shrink-0 w-10 h-10 rounded-xl flex items-center justify-center text-slate-300 bg-slate-800/60 border border-slate-700/60 hover:border-sky-500/50 transition-all"
            title="Capture snapshot"
          >
            📷
          </button>
          <button
            onClick={() => handleExecuteCommand()}
            className="shrink-0 px-4 h-10 rounded-xl bg-gradient-to-br from-[#38bdf8] to-[#0ea5e9] text-slate-950 font-bold text-sm hover:shadow-[0_0_20px_rgba(56,189,248,0.5)] transition-all"
          >
            Send
          </button>
        </div>
        <div className="text-[10px] text-slate-600 font-mono">
          core-0.1 · whisper | mediapipe · {onlineCount}/{liveAgents.length} agents
        </div>
      </div>
{/* Screenshot modal */}
      {showScreenshot && screenshotData && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4" onClick={() => setShowScreenshot(false)}>
          <div className="relative max-w-3xl w-full rounded-2xl bg-slate-900/90 border border-slate-700/60 p-3 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <button onClick={() => setShowScreenshot(false)} className="absolute top-2 right-2 w-8 h-8 rounded-lg bg-slate-800 text-slate-400 hover:text-white transition">✕</button>
            <img src={`data:image/png;base64,${screenshotData}`} alt="Desktop snapshot" className="w-full rounded-xl border border-slate-800" />
            <div className="pt-2 text-center text-xs text-slate-500">Live desktop snapshot</div>
          </div>
        </div>
      )}

      {/* Agent dispatch modal */}
      {showDispatch && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4" onClick={() => setShowDispatch(false)}>
          <div className="relative w-full max-w-3xl max-h-[85vh] rounded-2xl bg-slate-900/95 border border-slate-700/60 shadow-2xl flex flex-col overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800">
              <div>
                <div className="text-sm font-bold tracking-widest text-sky-300">FLEET DISPATCH</div>
                <div className="text-[11px] text-slate-500">Direct directive to a specialist agent</div>
              </div>
              <button onClick={() => setShowDispatch(false)} className="w-8 h-8 rounded-lg bg-slate-800 text-slate-400 hover:text-white transition">✕</button>
            </div>
            <div className="flex-1 overflow-y-auto p-5 space-y-3">
              {liveAgents.map((a) => (
                <div key={a.id} className={`flex items-start gap-3 p-3 rounded-xl border transition-all ${a.status === "ONLINE" ? "border-slate-700/60 hover:border-sky-500/50 bg-slate-800/40" : "border-slate-800 bg-slate-900/40 opacity-60"}`}>
                  <div className="w-9 h-9 rounded-lg flex items-center justify-center text-sm" style={{ background: `${a.accent}22`, color: a.accent }}>{a.icon ? <a.icon className="w-4 h-4" /> : "▦"}</div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold text-slate-100">{a.name}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${a.status === "ONLINE" ? "bg-emerald-500/15 text-emerald-300" : a.status === "BUSY" ? "bg-amber-500/15 text-amber-300" : "bg-slate-700/40 text-slate-400"}`}>{a.status}</span>
                    </div>
                    <div className="text-[11px] text-slate-500 truncate">{a.role}</div>
                  </div>
                  <button
                    onClick={() => handleDispatchToAgent(a)}
                    disabled={isAgentExecuting || a.status !== "ONLINE"}
                    className="shrink-0 px-3 h-8 rounded-lg text-[11px] font-semibold bg-sky-500/10 text-sky-300 border border-sky-500/30 hover:bg-sky-500/20 disabled:opacity-40 disabled:cursor-not-allowed transition"
                  >
                    {isAgentExecuting ? "…" : "Direct"}
                  </button>
                </div>
              ))}
              <div className="p-3 rounded-xl border border-slate-800 bg-slate-900/40">
                <textarea
                  value={agentDirectiveInput}
                  onChange={(e) => setAgentDirectiveInput(e.target.value)}
                  placeholder="Directive for the selected agent…"
                  className="w-full bg-transparent outline-none text-sm text-slate-100 placeholder:text-slate-600 resize-none h-20"
                />
              </div>
              {agentDirectiveResponse && (
                <div className="p-3 rounded-xl bg-sky-500/5 border border-sky-500/20 text-xs text-slate-300 whitespace-pre-wrap">{agentDirectiveResponse}</div>
              )}
            </div>
          </div>
        </div>
      )}
    </main>
  );
}



