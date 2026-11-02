"use client";

import {
  Activity,
  AlertCircle,
  ArrowUpRight,
  AudioLines,
  Check,
  ChevronDown,
  Circle,
  Clock3,
  Command,
  Cpu,
  ExternalLink,
  Globe2,
  KeyRound,
  LoaderCircle,
  LockKeyhole,
  MessageSquareText,
  Mic,
  Monitor,
  Radio,
  RefreshCw,
  Send,
  Settings2,
  ShieldCheck,
  Square,
  Volume2,
  X,
  Zap,
  CheckCircle2,
  Wifi,
  WifiOff,
  Database,
  Terminal,
  BarChart2,
  Network,
  HardDrive,
  MousePointer2,
  Eye,
  EyeOff,
  Layers,
} from "lucide-react";
import { Room, RoomEvent, Track } from "livekit-client";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

type Agent = {
  id: string;
  name: string;
  role?: string;
  status: string;
  latency_ms?: number | null;
  details?: string;
  desc?: string;
  endpoint?: string;
};

type FleetSnapshot = {
  status: string;
  scope?: string;
  timestamp?: string;
  agent_count?: number;
  status_counts?: Record<string, number>;
  agents: Agent[];
  note?: string;
};

type HostTelemetry = {
  status: string;
  cpu_percent?: number;
  cpu_cores?: number;
  ram_percent?: number;
  ram_total_gb?: number;
  ram_used_gb?: number;
  ram_avail_gb?: number;
  os?: string;
  operator?: string;
  timestamp?: string;
  error?: string;
};

type AutonomySnapshot = {
  autonomous_mode?: boolean;
  active_agent?: string | null;
  active_directive?: string | null;
  history_count?: number;
  recent_actions?: Array<{
    timestamp?: string;
    action_type?: string;
    target?: string;
    directive?: string;
    result?: string;
    success?: boolean;
  }>;
  agent_activity?: Record<string, {
    timestamp?: string;
    recorded_at?: string;
    directive?: string;
    result?: string;
    success?: boolean;
    action_type?: string;
  }>;
};

type ActivityItem = {
  id: number;
  at: string;
  command: string;
  reply: string;
  success: boolean;
};

const API_BASE_SESSION_KEY = "friday.control.apiBase";
const API_TOKEN_SESSION_KEY = "friday.control.apiToken";
const CONTROL_SESSION_KEY = "friday.control.session";
const CONTROL_SESSION_EXPIRY_KEY = "friday.control.sessionExpiry";

function apiBase(): string {
  if (typeof window === "undefined") return "";
  const saved = window.localStorage.getItem(API_BASE_SESSION_KEY)?.trim();
  if (saved) {
    const normalized = saved.replace(/\/$/, "");
    if (
      window.location.hostname === "localhost" &&
      normalized === "http://localhost:9000"
    ) {
      return "http://localhost:10000";
    }
    return normalized;
  }
  const configured = process.env.NEXT_PUBLIC_FRIDAY_API_URL?.trim();
  if (configured) return configured.replace(/\/$/, "");
  if (window.location.port === "3000") {
    return "https://friday-universe.duckdns.org/friday";
  }
  return window.location.origin;
}

function controlToken(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(CONTROL_SESSION_KEY)?.trim() ?? "";
}

function controlTokenFresh(): boolean {
  if (typeof window === "undefined") return false;
  if (!controlToken()) return false;
  const expiresAt = Number(window.localStorage.getItem(CONTROL_SESSION_EXPIRY_KEY) ?? "0");
  return Number.isFinite(expiresAt) && expiresAt * 1000 > Date.now() + 30_000;
}

async function ensureControlSession(force = false): Promise<string> {
  if (typeof window === "undefined") return "";
  if (!force && controlTokenFresh()) return controlToken();
  try {
    const response = await fetch(`${apiBase()}/api/control/session`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) return "";
    const token = typeof body?.token === "string" ? body.token : "";
    if (!token) return "";
    const expiresAt = Date.parse(String(body?.expires_at ?? "")) / 1000;
    window.localStorage.setItem(CONTROL_SESSION_KEY, token);
    window.localStorage.setItem(
      CONTROL_SESSION_EXPIRY_KEY,
      String(Number.isFinite(expiresAt) ? expiresAt : Date.now() / 1000 + 900),
    );
    return token;
  } catch {
    return "";
  }
}

function apiHeaders(json = false): HeadersInit {
  const headers: Record<string, string> = {};
  if (json) headers["Content-Type"] = "application/json";
  const token = typeof window === "undefined"
    ? ""
    : window.localStorage.getItem(API_TOKEN_SESSION_KEY)?.trim() ?? "";
  if (token) headers["X-FRIDAY-API-Key"] = token;
  const session = controlToken();
  if (session) headers["X-FRIDAY-Control-Token"] = session;
  return headers;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const send = async (): Promise<Response> => fetch(`${apiBase()}${path}`, {
    ...init,
    headers: { ...apiHeaders(Boolean(init?.body)), ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  let response = await send();
  if (response.status === 401 && !window.localStorage.getItem(API_TOKEN_SESSION_KEY)) {
    if (await ensureControlSession(true)) response = await send();
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return body as T;
}

function formatTime(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date);
}

function statusTone(status?: string): string {
  const value = (status ?? "").toUpperCase();
  if (["ONLINE", "OK", "READY", "CONNECTED", "SUCCESS"].includes(value)) return "good";
  if (["DEGRADED", "WARNING", "UNKNOWN"].includes(value)) return "warn";
  if (["OFFLINE", "DOWN", "ERROR", "UNAVAILABLE", "NOT_READY"].includes(value)) return "bad";
  return "muted";
}

const AGENT_ORDER = [
  "stratex",
  "inference",
  "cortex",
  "forge",
  "intelx",
  "vyralx",
  "memora",
  "futuris",
  "sentinel",
] as const;

const AGENT_ICONS: Record<string, React.ReactNode> = {
  stratex: <BarChart2 size={16} />,
  inference: <Network size={16} />,
  cortex: <Database size={16} />,
  forge: <Terminal size={16} />,
  intelx: <ShieldCheck size={16} />,
  vyralx: <Layers size={16} />,
  memora: <HardDrive size={16} />,
  futuris: <Eye size={16} />,
  sentinel: <Wifi size={16} />,
};

function Sparkline({ values, color, width = 120, height = 36 }: {
  values: number[];
  color: string;
  width?: number;
  height?: number;
}) {
  if (values.length < 2) return <svg width={width} height={height} />;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 1);
  const points = values.map((v, i) => {
    const x = (i / (values.length - 1)) * 100;
    const y = 100 - ((v - min) / span) * 90;
    return `${x},${y}`;
  }).join(" ");
  return (
    <svg width={width} height={height} viewBox="0 0 100 100" role="img" aria-label="Recent samples" className="sparkline">
      <path d={`M${points}`} fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={points.split(" ").at(-1)?.split(",")[0]} cy={points.split(" ").at(-1)?.split(",")[1]} r="2.5" fill={color} />
    </svg>
  );
}

function LiveKitVoicePanel() {
  const [status, setStatus] = useState<"idle" | "connecting" | "connected" | "error">("idle");
  const [message, setMessage] = useState("Voice disconnected");
  const [audioBlocked, setAudioBlocked] = useState(false);
  const [agentAudio, setAgentAudio] = useState(false);
  const roomRef = useRef<Room | null>(null);

  useEffect(() => () => {
    roomRef.current?.disconnect();
    roomRef.current = null;
    document.querySelectorAll("audio[data-livekit]").forEach((el) => el.remove());
  }, []);

  function clearAudioElements() {
    document.querySelectorAll("audio[data-livekit]").forEach((el) => el.remove());
  }

  async function toggleVoice() {
    if (status === "connected") {
      roomRef.current?.disconnect();
      roomRef.current = null;
      clearAudioElements();
      setAgentAudio(false);
      setAudioBlocked(false);
      setStatus("idle");
      setMessage("Voice disconnected");
      return;
    }

    setStatus("connecting");
    setMessage("Requesting voice room…");
    setAudioBlocked(false);
    setAgentAudio(false);

    const room = new Room({ adaptiveStream: true, dynacast: true });
    void room.startAudio().catch(() => {});

    try {
      const identity = `owner-${crypto.randomUUID().slice(0, 8)}`;
      const response = await fetch(`${apiBase()}/api/livekit/token?room=friday&identity=${encodeURIComponent(identity)}`, {
        headers: apiHeaders(),
        cache: "no-store",
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `LiveKit token request failed (${response.status})`);

      const attachAudio = (track: Track) => {
        if (track.kind !== Track.Kind.Audio) return;
        if (track.attachedElements.length > 0) return;
        const element = track.attach() as HTMLAudioElement;
        element.setAttribute("data-livekit", "true");
        element.autoplay = true;
        element.setAttribute("playsinline", "true");
        element.volume = 1.0;
        document.body.appendChild(element);
        element.play().catch((err) => {
          console.warn("LiveKit audio element play deferred:", err);
          setAudioBlocked(true);
          void room.startAudio().catch(() => {});
        });
      };

      room.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind !== Track.Kind.Audio) return;
        attachAudio(track);
        setAgentAudio(true);
        setMessage("FRIDAY is listening — speak now");
      });

      room.on(RoomEvent.TrackUnsubscribed, (track) => {
        track.detach().forEach((element) => element.remove());
      });

      room.on(RoomEvent.Disconnected, () => {
        setStatus("idle");
        setMessage("Voice disconnected");
        setAgentAudio(false);
        clearAudioElements();
      });

      room.on(RoomEvent.ConnectionStateChanged, (state) => {
        if (state === "connected") {
          setStatus("connected");
        } else if (state === "disconnected") {
          setStatus("idle");
        }
      });

      await room.connect(body.server_url, body.token);
      roomRef.current = room;
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Voice connection failed";
      setStatus("error");
      setMessage(msg);
      roomRef.current?.disconnect();
      roomRef.current = null;
      clearAudioElements();
    }
  }

  return (
    <article className="surface voice-panel">
      <div className="panel-head">
        <div className="panel-title">
          <div className="title-icon voice"><AudioLines size={18} /></div>
          <div>
            <h3>Voice</h3>
            <span className="subtitle">Real-time conversation with FRIDAY</span>
          </div>
        </div>
        <div className="panel-status">
          <span className={`state-dot ${status === "connected" ? "on" : status === "connecting" ? "pending" : status === "error" ? "off" : ""}`} />
          <span className={`state-label ${status}`}>{status === "connected" ? "Connected" : status === "connecting" ? "Connecting…" : status === "error" ? "Error" : "Disconnected"}</span>
        </div>
      </div>
      <p className="voice-message">{message}</p>
      {audioBlocked && <p className="voice-blocked"><AlertCircle size={12} /> Audio was blocked — click the room to allow playback</p>}
      <button className={`btn ${status === "connected" ? "btn-danger" : "btn-primary"}`} onClick={toggleVoice} disabled={status === "connecting"}>
        {status === "connecting" ? <LoaderCircle size={15} className="spin" /> : status === "connected" ? <Volume2 size={15} /> : <Mic size={15} />}
        {status === "connecting" ? "Connecting…" : status === "connected" ? "Disconnect" : "Connect"}
      </button>
    </article>
  );
}

export default function Page() {
  const [fleet, setFleet] = useState<FleetSnapshot | null>(null);
  const [fleetError, setFleetError] = useState("");
  const [telemetry, setTelemetry] = useState<HostTelemetry | null>(null);
  const [telemetryError, setTelemetryError] = useState("");
  const [autonomy, setAutonomy] = useState<AutonomySnapshot | null>(null);
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [connected, setConnected] = useState<"checking" | "online" | "offline">("checking");
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [cpuHistory, setCpuHistory] = useState<number[]>([]);
  const [ramHistory, setRamHistory] = useState<number[]>([]);
  const [laptops, setLaptops] = useState<Array<{ laptop_id: string; online?: boolean; connected_at?: string; last_seen?: string }>>([]);
  const [laptopError, setLaptopError] = useState("");
  const [laptopOutput, setLaptopOutput] = useState("");
  const [laptopBusy, setLaptopBusy] = useState("");
  const [laptopUrl, setLaptopUrl] = useState("https://friday-universe.duckdns.org/");
  const [command, setCommand] = useState("");
  const [busy, setBusy] = useState(false);
  const [commandError, setCommandError] = useState("");
  const [reply, setReply] = useState("");
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [agentDirective, setAgentDirective] = useState("");
  const [agentBusy, setAgentBusy] = useState(false);
  const [agentResult, setAgentResult] = useState("");
  const [controlReady, setControlReady] = useState(false);
  const [now, setNow] = useState(new Date());
  const [hydrated, setHydrated] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [draftBase, setDraftBase] = useState("");
  const [draftToken, setDraftToken] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const displayNow = useMemo(() => hydrated ? new Date(now) : new Date(), [hydrated, now]);
  const onlineCount = useMemo(() => fleet?.agents?.filter((a) => a.status === "ONLINE").length ?? 0, [fleet]);

  const refresh = useCallback(async (manual = false) => {
    if (manual) setRefreshing(true);
    const [fleetResult, telemetryResult, autonomyResult, healthResult, laptopResult] = await Promise.allSettled([
      requestJson<FleetSnapshot>("/api/agents/status"),
      requestJson<HostTelemetry>("/api/system_telemetry"),
      requestJson<AutonomySnapshot>("/api/autonomous/status"),
      requestJson<Record<string, unknown>>("/api/health"),
      requestJson<{ devices?: Array<{ laptop_id: string; online?: boolean; connected_at?: string; last_seen?: string }> }>("/api/laptop/devices"),
    ]);

    if (fleetResult.status === "fulfilled") {
      setFleet(fleetResult.value);
      setFleetError("");
      setConnected("online");
    } else {
      setFleetError(fleetResult.reason instanceof Error ? fleetResult.reason.message : "Fleet status unavailable");
      setConnected("offline");
    }
    if (telemetryResult.status === "fulfilled") {
      const data = telemetryResult.value;
      setTelemetry(data);
      if (data.status === "ok" && typeof data.cpu_percent === "number") {
        setCpuHistory((current) => [...current, data.cpu_percent!].slice(-60));
      }
      if (data.status === "ok" && typeof data.ram_percent === "number") {
        setRamHistory((current) => [...current, data.ram_percent!].slice(-60));
      }
      setTelemetryError(data.status === "ok" ? "" : data.error ?? "Host telemetry unavailable");
    } else {
      setTelemetry(null);
      setTelemetryError(telemetryResult.reason instanceof Error ? telemetryResult.reason.message : "Host telemetry unavailable");
    }
    if (autonomyResult.status === "fulfilled") setAutonomy(autonomyResult.value);
    if (healthResult.status === "fulfilled") setHealth(healthResult.value);
    if (laptopResult.status === "fulfilled") {
      setLaptops(Array.isArray(laptopResult.value.devices) ? laptopResult.value.devices! : []);
      setLaptopError("");
    } else {
      setLaptopError(laptopResult.reason instanceof Error ? laptopResult.reason.message : "Could not list connected laptops.");
    }
    if (manual) setRefreshing(false);
  }, []);

  useEffect(() => {
    setHydrated(true);
    if (typeof window !== "undefined") {
      const base = window.localStorage.getItem(API_BASE_SESSION_KEY);
      if (!base || /localhost:10000|localhost:9000/.test(base)) {
        window.localStorage.setItem(API_BASE_SESSION_KEY, "https://friday-universe.duckdns.org");
      }
      if (!window.localStorage.getItem(API_TOKEN_SESSION_KEY)) {
        void ensureControlSession(true).then((token) => setControlReady(Boolean(token)));
      }
    }
    void ensureControlSession().then((token) => setControlReady(Boolean(token)));
    const initial = window.setTimeout(() => { void refresh(); void pollActivity(); }, 0);
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") { void refresh(); void pollActivity(); }
    }, 30_000);
    const clock = window.setInterval(() => setNow(new Date()), 1_000);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
      window.clearInterval(clock);
    };
  }, [refresh]);

  async function pollActivity() {
    try {
      const data = await requestJson<AutonomySnapshot>("/api/autonomous/status");
      setAutonomy(data);
    } catch {
      // ignore
    }
  }

  async function submitCommand(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const clean = command.trim();
    if (!clean || busy) return;
    setBusy(true);
    setCommandError("");
    setReply("");
    try {
      const result = await requestJson<{ reply?: string; autonomous_mode?: boolean; mode?: string }>("/api/command", {
        method: "POST",
        body: JSON.stringify({ input: clean }),
      });
      const answer = result.reply || result.mode || "FRIDAY accepted the command.";
      setReply(answer);
      setActivity((current) => [{ id: Date.now(), at: new Date().toISOString(), command: clean, reply: answer, success: true }, ...current].slice(0, 20));
      void refresh();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Command failed.";
      setCommandError(message);
      setActivity((current) => [{ id: Date.now(), at: new Date().toISOString(), command: clean, reply: message, success: false }, ...current].slice(0, 20));
    } finally {
      setBusy(false);
      setCommand("");
    }
  }

  async function toggleAutonomy() {
    if (busy) return;
    setBusy(true);
    setCommandError("");
    try {
      const result = await requestJson<{ autonomous_mode?: boolean }>("/api/autonomous/toggle", { method: "POST" });
      if (typeof result.autonomous_mode === "boolean") {
        setAutonomy((current) => ({ ...(current ?? {}), autonomous_mode: result.autonomous_mode }));
        setReply(`Autonomous mode is now ${result.autonomous_mode ? "on" : "off"}.`);
      } else {
        setReply("The server accepted the toggle request but returned no mode value.");
      }
    } catch (error) {
      setCommandError(error instanceof Error ? error.message : "Could not change autonomous mode.");
    } finally {
      setBusy(false);
    }
  }

  async function runAgentTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const clean = agentDirective.trim();
    if (!clean || agentBusy || !selectedAgent) return;
    setAgentBusy(true);
    setAgentResult("");
    setCommandError("");
    try {
      const result = await requestJson<{ reply?: string; metadata?: Record<string, unknown> }>(
        `/api/agents/${encodeURIComponent(selectedAgent)}/task`,
        { method: "POST", body: JSON.stringify({ directive: clean }) },
      );
      const answer = result.reply || `${selectedAgent} returned no reply text.`;
      setAgentResult(answer);
      setActivity((current) => [{ id: Date.now(), at: new Date().toISOString(), command: `@${selectedAgent} ${clean}`, reply: answer, success: true }, ...current].slice(0, 20));
      setAgentDirective("");
      void refresh();
    } catch (error) {
      const message = error instanceof Error ? error.message : "The agent task could not be sent.";
      setAgentResult(message);
      setActivity((current) => [{ id: Date.now(), at: new Date().toISOString(), command: `@${selectedAgent} ${clean}`, reply: message, success: false }, ...current].slice(0, 20));
    } finally {
      setAgentBusy(false);
    }
  }

  async function runLaptopCommand(command: string, args: Record<string, unknown> = {}) {
    if (!laptops.length) {
      setLaptopError("No laptop is connected yet. Start the bridge on your laptop first.");
      return;
    }
    const device = laptops.find((item) => item.online !== false) ?? laptops[0];
    setLaptopBusy(command);
    setLaptopOutput("");
    setLaptopError("");
    try {
      const result = await requestJson<Record<string, unknown>>(
        `/api/laptop/${encodeURIComponent(device.laptop_id)}/command`,
        { method: "POST", body: JSON.stringify({ command, args, timeout: 30 }) },
      );
      const output = result.output ?? result.error ?? result;
      setLaptopOutput(typeof output === "string" ? output : JSON.stringify(output, null, 2));
    } catch (error) {
      setLaptopError(error instanceof Error ? error.message : "The laptop command failed.");
    } finally {
      setLaptopBusy("");
    }
  }

  async function triggerRepair() {
    if (busy) return;
    setBusy(true);
    setCommandError("");
    try {
      const result = await requestJson<Record<string, unknown>>("/api/autonomous/repair", { method: "POST" });
      const summary = String(result.summary ?? result.status ?? "Self-repair sweep requested.");
      setReply(summary);
      void refresh();
    } catch (error) {
      setCommandError(error instanceof Error ? error.message : "The self-repair sweep could not be started.");
    } finally {
      setBusy(false);
    }
  }

  async function cancelTasks() {
    if (busy) return;
    setBusy(true);
    try {
      const result = await requestJson<Record<string, unknown>>("/api/autonomous/cancel", { method: "POST" });
      setReply(String(result.message ?? result.status ?? "Active tasks cancelled."));
    } catch (error) {
      setCommandError(error instanceof Error ? error.message : "Could not cancel tasks.");
    } finally {
      setBusy(false);
    }
  }

  function saveConnection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const base = draftBase.trim().replace(/\/$/, "");
    const token = draftToken.trim();
    if (base) window.localStorage.setItem(API_BASE_SESSION_KEY, base);
    if (token) window.localStorage.setItem(API_TOKEN_SESSION_KEY, token);
    setShowSettings(false);
    setControlReady(false);
    void ensureControlSession(true).then((t) => setControlReady(Boolean(t)));
    void refresh(true);
  }

  function openSettings() {
    setDraftBase(apiBase());
    setDraftToken("");
    setShowSettings(true);
  }

  function closeSettings() {
    setShowSettings(false);
  }

  if (!hydrated) {
    return (
      <main className="shell loading">
        <div className="loader" aria-label="Loading FRIDAY dashboard">
          <svg viewBox="0 0 48 48"><circle cx="24" cy="24" r="20" stroke="currentColor" strokeWidth="3" fill="none" strokeDasharray="125.6" strokeDashoffset="31.4"><animateTransform attributeName="transform" type="rotate" from="0 24 24" to="360 24 24" dur="1s" repeatCount="indefinite" /></circle></svg>
        </div>
      </main>
    );
  }

  const agents = fleet?.agents ?? [];
  const sortedAgents = [...agents].sort((a, b) => {
    const ai = AGENT_ORDER.indexOf(a.id as typeof AGENT_ORDER[number]);
    const bi = AGENT_ORDER.indexOf(b.id as typeof AGENT_ORDER[number]);
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });

  const selected = selectedAgent ? sortedAgents.find((a) => a.id === selectedAgent) : null;
  const agentActivity = autonomy?.agent_activity ?? {};

  return (
    <main className="shell">
      <aside className="sidebar" aria-label="Navigation">
        <a className="brand" href="#top" aria-label="FRIDAY home">
          <span className="brand-mark"><AudioLines size={20} strokeWidth={2.2} /></span>
          <span className="brand-copy"><strong>FRIDAY</strong><small>UNIVERSE CONTROL</small></span>
        </a>
        <nav className="side-nav" aria-label="Main navigation">
          <a className="nav-link active" href="#command"><Command size={17} />Command</a>
          <a className="nav-link" href="#apartment"><Globe2 size={17} />Apartment</a>
          <a className="nav-link" href="#laptop"><Monitor size={17} />Laptop</a>
          <a className="nav-link" href="#telemetry"><Activity size={17} />Telemetry</a>
          <a className="nav-link" href="#activity"><MessageSquareText size={17} />Session</a>
        </nav>
        <div className="sidebar-spacer" />
        <div className="sidebar-status">
          <div className="status-row">
            <span className={`status-dot ${connected}`} />
            <span>{connected === "online" ? "API responding" : connected === "offline" ? "API unavailable" : "Connecting…"}</span>
          </div>
          <button className="text-btn" onClick={openSettings}><Settings2 size={14} /> Connection</button>
        </div>
        <div className="sidebar-footer"><span className="user-avatar">S</span><span><strong>Surendra</strong><small>Owner</small></span></div>
      </aside>

      <section className="main" id="top">
        <header className="topbar">
          <div className="breadcrumb"><span>Workspace</span><span className="slash">/</span><strong>Command center</strong></div>
          <div className="top-actions">
            <div className="clock"><Clock3 size={15} /><span>{displayNow.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</span></div>
            <button className="icon-btn" title="Refresh live data" onClick={() => void refresh(true)} disabled={refreshing}><RefreshCw size={16} className={refreshing ? "spin" : ""} /></button>
            <button className="icon-btn" title="Settings" onClick={openSettings}><KeyRound size={14} /></button>
          </div>
        </header>

        <div className="content">
          {/* COMMAND SECTION */}
          <section className="section" id="command">
            <div className="section-header">
              <div className="section-title">
                <div className="eyebrow"><span className="eyebrow-line" />PERSONAL ASSISTANT</div>
                <h1>Good {displayNow.getHours() < 12 ? "morning" : displayNow.getHours() < 18 ? "afternoon" : "evening"}, Surendra.</h1>
              </div>
              <div className="live-badge">
                <span className={`status-dot ${connected}`} />
                <span>{connected === "online" ? "API responding" : "API unavailable"}</span>
              </div>
            </div>

            <article className="card command-card">
              <div className="card-head">
                <div className="card-title">
                  <div className="title-icon cmd"><AudioLines size={18} /></div>
                  <div>
                    <h3>Talk to FRIDAY</h3>
                    <span className="subtitle">Commands run on the connected FRIDAY host.</span>
                  </div>
                </div>
                <span className={`tag ${controlReady ? "granted" : "pending"}`}>
                  <LockKeyhole size={11} />
                  {controlReady ? "Control active" : "Requesting…"}
                </span>
              </div>
              <form className="command-form" onSubmit={submitCommand}>
                <textarea
                  value={command}
                  onChange={(event) => setCommand(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      event.currentTarget.form?.requestSubmit();
                    }
                  }}
                  placeholder="Ask FRIDAY to do something on your laptop or across the Universe…"
                  aria-label="Command for FRIDAY"
                  rows={2}
                  disabled={busy}
                />
                <div className="command-footer">
                  <span className="hint"><kbd>Enter</kbd> send · <kbd>Shift + Enter</kbd> new line</span>
                  <button className={`btn ${busy ? "btn-disabled" : "btn-primary"}`} type="submit" disabled={busy || !command.trim()}>
                    {busy ? <LoaderCircle size={15} className="spin" /> : <Send size={15} />}
                    {busy ? "Working" : "Send"}
                  </button>
                </div>
              </form>
              {commandError && <div className="inline-error"><AlertCircle size={14} />{commandError}{/key|required|401|403|503/i.test(commandError) && <button onClick={openSettings} className="err-link">Set connection</button>}</div>}
              {reply && <div className="reply-card"><div className="reply-label"><span className="reply-dot" />FRIDAY RESPONSE</div><p>{reply}</p></div>}
            </article>

            <div className="metrics-row">
              <article className="card metric-card">
                <div className="card-head">
                  <div className="card-title">
                    <div className="title-icon cpu"><Cpu size={18} /></div>
                    <div>
                      <h3>CPU Load</h3>
                      <span className="subtitle">{telemetry?.cpu_cores ?? "—"} cores</span>
                    </div>
                  </div>
                  <span className={`state-badge ${statusTone(String(telemetry?.status ?? ""))}`}>{telemetry?.status === "ok" ? `${telemetry.cpu_percent}%` : "Unavailable"}</span>
                </div>
                <div className="metric-value-row">
                  <span className="metric-big">{telemetry?.status === "ok" && typeof telemetry.cpu_percent === "number" ? telemetry.cpu_percent : "—"}<small>%</small></span>
                  <Sparkline values={cpuHistory} color="#8de6cf" width={140} height={40} />
                </div>
              </article>

              <article className="card metric-card">
                <div className="card-head">
                  <div className="card-title">
                    <div className="title-icon mem"><Activity size={18} /></div>
                    <div>
                      <h3>Memory</h3>
                      <span className="subtitle">{telemetry?.ram_total_gb ?? "—"} GB total</span>
                    </div>
                  </div>
                  <span className={`state-badge ${statusTone(String(telemetry?.status ?? ""))}`}>{telemetry?.status === "ok" ? `${telemetry.ram_percent}%` : "Unavailable"}</span>
                </div>
                <div className="metric-value-row">
                  <span className="metric-big">{telemetry?.status === "ok" && typeof telemetry.ram_percent === "number" ? telemetry.ram_percent : "—"}<small>%</small></span>
                  <Sparkline values={ramHistory} color="#b9a6ff" width={140} height={40} />
                </div>
              </article>

              <article className="card metric-card">
                <div className="card-head">
                  <div className="card-title">
                    <div className="title-icon fleet"><Globe2 size={18} /></div>
                    <div>
                      <h3>Agent Reachability</h3>
                      <span className="subtitle">{fleet?.agent_count ?? 9} agents</span>
                    </div>
                  </div>
                  <span className={`state-badge ${statusTone(fleet?.status)}`}>{fleet?.status ?? "Unknown"}</span>
                </div>
                <div className="metric-value-row">
                  <span className="metric-big">{onlineCount}<small> / {fleet?.agent_count ?? agents.length}</small></span>
                  <div className="mini-dots">
                    {sortedAgents.map((a) => (
                      <span key={a.id} className={`mini-dot ${statusTone(a.status)}`} title={`${a.name}: ${a.status}`} />
                    ))}
                  </div>
                </div>
              </article>

              <article className="card metric-card">
                <div className="card-head">
                  <div className="card-title">
                    <div className="title-icon auto"><Zap size={18} /></div>
                    <div>
                      <h3>Autonomous Mode</h3>
                      <span className="subtitle">{autonomy?.history_count ?? "—"} recorded</span>
                    </div>
                  </div>
                  <span className={`state-badge ${autonomy?.autonomous_mode ? "good" : "muted"}`}>{autonomy?.autonomous_mode ? "Enabled" : "Manual"}</span>
                </div>
                <div className="metric-value-row">
                  <button className={`btn ${autonomy?.autonomous_mode ? "btn-danger" : "btn-primary"}`} onClick={toggleAutonomy} disabled={busy || !autonomy}>
                    {autonomy?.autonomous_mode ? <Zap size={15} /> : <Radio size={15} />}
                    {autonomy?.autonomous_mode ? "Disable" : "Enable"}
                  </button>
                  <div className="mini-dots">
                    {Object.entries(agentActivity).map(([id, act]) => (
                      <span key={id} className={`mini-dot ${act.success ? "good" : "bad"}`} title={`${id}: ${act.directive?.slice(0, 30)}`} />
                    ))}
                  </div>
                </div>
              </article>
            </div>
          </section>

          {/* AGENT APARTMENT */}
          <section className="section" id="apartment">
            <div className="section-header">
              <div className="section-title">
                <div className="eyebrow"><span className="eyebrow-line" />LIVE FLEET</div>
                <h2>Agent Apartment</h2>
              </div>
              <div className="section-meta">
                <span className="updated-at">{autonomy?.active_agent ? `Active: ${autonomy.active_agent}` : "All agents standing by"}</span>
              </div>
            </div>

            <div className="apartment-grid">
              {sortedAgents.map((agent) => {
                const last = autonomy?.recent_actions?.find((a) => a.target?.toUpperCase() === agent.name?.toUpperCase());
                const activityRecord = agentActivity[agent.id];
                const isActive = autonomy?.active_agent?.toLowerCase() === agent.id;
                const siteUrl = `https://friday-universe.duckdns.org/${agent.id}`;
                const Icon = AGENT_ICONS[agent.id] || <Database size={16} />;
                return (
                  <article key={agent.id} className={`apartment-room ${isActive ? "active" : ""} ${statusTone(agent.status)}`}>
                    <button
                      type="button"
                      className="room-link"
                      onClick={() => window.open(siteUrl, "_blank", "noopener,noreferrer")}
                      aria-label={`Open ${agent.name} site`}
                      title={`Open ${agent.name} site`}
                    >
                      <ArrowUpRight size={13} />
                    </button>
                    <button
                      type="button"
                      className="room-body"
                      onClick={() => setSelectedAgent(selectedAgent === agent.id ? null : agent.id)}
                      aria-label={`Show ${agent.name} details and send a task`}
                    >
                      <div className="room-head">
                        <span className={`state-dot ${statusTone(agent.status) === "good" ? "on" : statusTone(agent.status) === "bad" ? "off" : "pending"}`} />
                        <div className="room-identity">
                          <div className="room-name-row">
                            <strong>{agent.name}</strong>
                            <span className="room-id">{agent.id}</span>
                          </div>
                          <div className="room-role">{agent.role || "Specialist Agent"}</div>
                        </div>
                        <div className="room-icon">
                          {Icon}
                        </div>
                      </div>
                      <div className="room-status-row">
                        <span className={`status-pill ${statusTone(agent.status)}`}>{agent.status}</span>
                        <span className="room-latency">{typeof agent.latency_ms === "number" ? `${Math.round(agent.latency_ms)} ms` : "—"}</span>
                      </div>
                      <div className="room-task">{activityRecord ? activityRecord.directive : last ? last.directive : "Idle — awaiting directive"}</div>
                      {(activityRecord || last) && (
                        <div className={`room-result ${(activityRecord || last)!.success ? "good" : "bad"}`}>
                          {(activityRecord || last)!.success ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}
                          <span>{String((activityRecord || last)!.result ?? "").slice(0, 80)}</span>
                        </div>
                      )}
                    </button>
                  </article>
                );
              })}
            </div>
          </section>

          {/* SELECTED AGENT DETAIL */}
          {selected && (
            <section className="section" id="agent-detail">
              <article className="card detail-card">
                <div className="card-head">
                  <div className="card-title">
                    <div className="title-icon">{AGENT_ICONS[selected.id] || <Database size={18} />}</div>
                    <div>
                      <h3>{selected.name}</h3>
                      <span className="subtitle">{selected.role || "Specialist Agent"}</span>
                    </div>
                  </div>
                  <div className="card-actions">
                    <a className="btn btn-ghost" href={`https://friday-universe.duckdns.org/${selected.id}`} target="_blank" rel="noreferrer"><ArrowUpRight size={14} />Open site</a>
                    <button className="btn btn-ghost" onClick={() => setSelectedAgent(null)}><X size={14} /></button>
                  </div>
                </div>
                <p className="detail-desc">{selected.details || selected.desc || "No additional description was returned by the service."}</p>
                <div className="detail-meta">
                  <div><strong>Endpoint</strong><span>{selected.endpoint || "not exposed"}</span></div>
                  <div><strong>Latency</strong><span>{typeof selected.latency_ms === "number" ? `${Math.round(selected.latency_ms)} ms` : "not reported"}</span></div>
                </div>
                <form className="detail-form" onSubmit={runAgentTask}>
                  <label htmlFor="agent-directive">Send {selected.name} a task</label>
                  <div className="detail-form-row">
                    <input
                      id="agent-directive"
                      value={agentDirective}
                      onChange={(event) => setAgentDirective(event.target.value)}
                      placeholder={`e.g. ${selected.id === "forge" ? "run the test suite and report failures" : selected.id === "intelx" ? "research this week's macro news" : "report status and current workload"}`}
                      disabled={agentBusy}
                    />
                    <button className={`btn ${agentBusy ? "btn-disabled" : "btn-primary"}`} type="submit" disabled={agentBusy || !agentDirective.trim()}>
                      {agentBusy ? <LoaderCircle size={15} className="spin" /> : <Send size={15} />}
                      {agentBusy ? "Dispatching" : "Dispatch"}
                    </button>
                  </div>
                </form>
                {agentResult && <div className="reply-card compact"><div className="reply-label"><span className="reply-dot" />{selected.name.toUpperCase()} RESPONSE</div><p>{agentResult}</p></div>}
              </article>
            </section>
          )}

          {/* LAPTOP CONTROL */}
          <section className="section" id="laptop">
            <div className="section-header">
              <div className="section-title">
                <div className="eyebrow"><span className="eyebrow-line" />DEVICE CONTROL</div>
                <h2>Laptop Control</h2>
              </div>
              <div className="section-meta">
                <span className="updated-at">{laptops.length ? `${laptops.filter((item) => item.online !== false).length} connected` : "No laptop connected"}</span>
                <button className="btn btn-ghost" onClick={() => void refresh()} disabled={refreshing}><RefreshCw size={14} className={refreshing ? "spin" : ""} /></button>
              </div>
            </div>

            {laptopError && <div className="inline-error"><AlertCircle size={14} />{laptopError}</div>}

            {laptops.length === 0 ? (
              <article className="card empty-card">
                <div className="empty-state">
                  <div className="empty-icon"><Monitor size={24} /></div>
                  <strong>Your laptop is not connected</strong>
                  <p>Run the bridge on your laptop once. It dials out to FRIDAY, so no ports or router changes are needed.</p>
                  <code className="cmd">python scripts/laptop_bridge_client.py</code>
                  <p className="hint">Set <code>FRIDAY_API_KEY</code> and <code>FRIDAY_BRIDGE_URL</code> first. The same control session that powers this page authorises the tunnel.</p>
                </div>
              </article>
            ) : (
              <>
                <article className="card devices-card">
                  <div className="card-head">
                    <div className="card-title">
                      <div className="title-icon"><Monitor size={18} /></div>
                      <div>
                        <h3>Connected Devices</h3>
                        <span className="subtitle">{laptops.filter((item) => item.online !== false).length} online</span>
                      </div>
                    </div>
                  </div>
                  <div className="devices-list">
                    {laptops.map((device) => (
                      <div key={device.laptop_id} className="device-row">
                        <span className={`state-dot ${device.online === false ? "off" : "on"}`} />
                        <strong>{device.laptop_id}</strong>
                        <span className="device-state">{device.online === false ? "Offline" : "Online"}</span>
                      </div>
                    ))}
                  </div>
                </article>

                <article className="card actions-card">
                  <div className="card-head">
                    <div className="card-title">
                      <div className="title-icon"><MousePointer2 size={18} /></div>
                      <div>
                        <h3>Actions</h3>
                        <span className="subtitle">Commands sent to the laptop</span>
                      </div>
                    </div>
                    <div className="action-grid">
                      <button className={`btn-action ${laptopBusy === "system_info" ? "busy" : ""}`} onClick={() => void runLaptopCommand("system_info")} disabled={Boolean(laptopBusy)}>
                        <Cpu size={16} />
                        <span>System Info</span>
                        {laptopBusy === "system_info" && <LoaderCircle size={14} className="spin" />}
                      </button>
                      <button className={`btn-action ${laptopBusy === "screenshot" ? "busy" : ""}`} onClick={() => void runLaptopCommand("screenshot")} disabled={Boolean(laptopBusy)}>
                        <Monitor size={16} />
                        <span>Screenshot</span>
                        {laptopBusy === "screenshot" && <LoaderCircle size={14} className="spin" />}
                      </button>
                      <button className={`btn-action ${laptopBusy === "notify" ? "busy" : ""}`} onClick={() => void runLaptopCommand("notify", { title: "FRIDAY", message: "Laptop control is working." })} disabled={Boolean(laptopBusy)}>
                        <Zap size={16} />
                        <span>Notify</span>
                        {laptopBusy === "notify" && <LoaderCircle size={14} className="spin" />}
                      </button>
                      <button className={`btn-action ${laptopBusy === "open_url" ? "busy" : ""}`} onClick={() => void runLaptopCommand("open_url", { url: laptopUrl })} disabled={Boolean(laptopBusy)}>
                        <ArrowUpRight size={16} />
                        <span>Open URL</span>
                        {laptopBusy === "open_url" && <LoaderCircle size={14} className="spin" />}
                      </button>
                    </div>
                    <div className="url-field">
                      <label>URL to open<input value={laptopUrl} onChange={(event) => setLaptopUrl(event.target.value)} inputMode="url" /></label>
                    </div>
                  </div>
                </article>

                {laptopOutput && (
                  <article className="card output-card">
                    <div className="card-head">
                      <div className="card-title">
                        <div className="title-icon"><Terminal size={18} /></div>
                        <div>
                          <h3>Output</h3>
                          <span className="subtitle">Raw evidence from the laptop</span>
                        </div>
                      </div>
                    </div>
                    <pre className="output-pre">{laptopOutput}</pre>
                  </article>
                )}
              </>
            )}
          </section>

          {/* TELEMETRY DETAIL */}
          <section className="section" id="telemetry">
            <div className="section-header">
              <div className="section-title">
                <div className="eyebrow"><span className="eyebrow-line" />HOST TELEMETRY</div>
                <h2>Connected Host</h2>
              </div>
              <div className="section-meta">
                <span className="updated-at">{telemetry?.timestamp ? `Sampled ${formatTime(telemetry.timestamp)}` : "No data"}</span>
                <button className="btn btn-ghost" onClick={() => void refresh(true)} disabled={refreshing}><RefreshCw size={14} className={refreshing ? "spin" : ""} /></button>
              </div>
            </div>
            <div className="telemetry-grid">
              <article className="card info-card">
                <div className="info-row"><span>System</span><strong>{telemetry?.os || (telemetryError ? "Unavailable" : "Waiting…")}</strong></div>
                <div className="info-row"><span>Operator</span><strong>{telemetry?.operator || "Not reported"}</strong></div>
                <div className="info-row"><span>CPU Cores</span><strong>{telemetry?.cpu_cores ?? "—"}</strong></div>
                <div className="info-row"><span>Total RAM</span><strong>{telemetry?.ram_total_gb ?? "—"} GB</strong></div>
                <div className="info-row"><span>Available RAM</span><strong>{telemetry?.ram_avail_gb ?? "—"} GB</strong></div>
                <div className="info-row"><span>Health</span><strong className={`state-badge ${statusTone(String(health?.status ?? ""))}`}>{String(health?.status ?? "UNKNOWN")}</strong></div>
              </article>
              <article className="card chart-card">
                <div className="card-head">
                  <div className="card-title">
                    <div className="title-icon"><BarChart2 size={18} /></div>
                    <div>
                      <h3>CPU History</h3>
                      <span className="subtitle">Last 60 samples</span>
                    </div>
                  </div>
                </div>
                <div className="chart-large">
                  <Sparkline values={cpuHistory} color="#8de6cf" width={400} height={140} />
                </div>
              </article>
              <article className="card chart-card">
                <div className="card-head">
                  <div className="card-title">
                    <div className="title-icon"><Activity size={18} /></div>
                    <div>
                      <h3>Memory History</h3>
                      <span className="subtitle">Last 60 samples</span>
                    </div>
                  </div>
                </div>
                <div className="chart-large">
                  <Sparkline values={ramHistory} color="#b9a6ff" width={400} height={140} />
                </div>
              </article>
            </div>
          </section>

          {/* SESSION ACTIVITY */}
          <section className="section" id="activity">
            <div className="section-header">
              <div className="section-title">
                <div className="eyebrow"><span className="eyebrow-line" />SESSION LOG</div>
                <h2>Recent Commands</h2>
              </div>
              <div className="section-meta">
                <span className="activity-count">{activity.length}</span>
                <button className="text-btn" onClick={() => setActivity([])} disabled={activity.length === 0}>Clear</button>
              </div>
            </div>
            <article className="card activity-card">
              {activity.length === 0 ? (
                <div className="empty-state">
                  <div className="empty-icon"><MessageSquareText size={24} /></div>
                  <strong>No commands yet</strong>
                  <p>Commands you send here will appear in this session log.</p>
                </div>
              ) : (
                <div className="activity-list">
                  {activity.map((item) => (
                    <div key={item.id} className={`activity-item ${item.success ? "good" : "bad"}`}>
                      <div className="activity-result">
                        {item.success ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
                      </div>
                      <div className="activity-copy">
                        <strong>{item.command}</strong>
                        <p>{item.reply}</p>
                        <time>{formatTime(item.at)}</time>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </article>
          </section>

          {/* VOICE PANEL */}
          <section className="section" id="voice">
            <LiveKitVoicePanel />
          </section>

          {/* CONTROL ACTIONS */}
          <section className="section" id="controls">
            <div className="section-header">
              <div className="section-title">
                <div className="eyebrow"><span className="eyebrow-line" />CONTROL</div>
                <h2>Task Controls</h2>
              </div>
            </div>
            <div className="control-grid">
              <article className="card control-card">
                <div className="card-head">
                  <div className="card-title">
                    <div className="title-icon"><Square size={18} /></div>
                    <div>
                      <h3>Cancel Tasks</h3>
                      <span className="subtitle">Stop all active autonomous tasks</span>
                    </div>
                  </div>
                </div>
                <button className="btn btn-danger full-width" onClick={cancelTasks} disabled={busy}>
                  <Square size={15} /> Cancel Active Tasks
                </button>
              </article>
              <article className="card control-card">
                <div className="card-head">
                  <div className="card-title">
                    <div className="title-icon"><Zap size={18} /></div>
                    <div>
                      <h3>Self-Repair</h3>
                      <span className="subtitle">Run autonomous repair sweep</span>
                    </div>
                  </div>
                </div>
                <button className="btn btn-primary full-width" onClick={triggerRepair} disabled={busy}>
                  <Zap size={15} /> Self-Repair Sweep
                </button>
              </article>
              <article className="card control-card">
                <div className="card-head">
                  <div className="card-title">
                    <div className="title-icon"><Settings2 size={18} /></div>
                    <div>
                      <h3>Connection</h3>
                      <span className="subtitle">Configure API endpoint and key</span>
                    </div>
                  </div>
                </div>
                <button className="btn btn-ghost full-width" onClick={openSettings}>
                  <Settings2 size={15} /> Connection Settings
                </button>
              </article>
            </div>
            <div className="control-foot">
              <LockKeyhole size={12} />
              <span>{controlReady || autonomy?.autonomous_mode ? "Control session active" : "Control session unavailable"} · expires automatically</span>
            </div>
          </section>

          <footer className="footer">
            <span>FRIDAY · PERSONAL AI CONTROL ROOM</span>
            <span>Fleet scope: {fleet?.scope || "not available"}</span>
            <a href="/api/health" target="_blank" rel="noreferrer">API health <ExternalLink size={12} /></a>
          </footer>
        </div>
      </section>

      {showSettings && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeSettings(); }}>
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
            <div className="modal-head">
              <div className="modal-title">
                <div className="eyebrow"><span className="eyebrow-line" />API CONNECTION</div>
                <h2 id="settings-title">Connect to FRIDAY</h2>
              </div>
              <button className="icon-btn" onClick={closeSettings} aria-label="Close settings"><X size={16} /></button>
            </div>
            <p className="modal-desc">Use your local FRIDAY API for laptop control, or enter a remote service URL. A remote control API key is required by the server. The key is held only for this browser tab.</p>
            <form onSubmit={saveConnection} className="modal-form">
              <label>FRIDAY API URL<input value={draftBase} onChange={(event) => setDraftBase(event.target.value)} placeholder="https://friday-universe.duckdns.org" inputMode="url" /></label>
              <label>Control API key <span className="optional">optional for localhost</span><input type="password" autoComplete="off" value={draftToken} onChange={(event) => setDraftToken(event.target.value)} placeholder="Paste key from your private service configuration" /></label>
              <div className="modal-warning"><LockKeyhole size={14} /><span>Never paste a key into a shared device. This UI does not send the key anywhere except the configured FRIDAY API.</span></div>
              <div className="modal-actions">
                <button type="button" className="btn btn-ghost" onClick={() => { window.localStorage.removeItem(API_BASE_SESSION_KEY); window.localStorage.removeItem(API_TOKEN_SESSION_KEY); setDraftBase(apiBase()); setDraftToken(""); }}>Reset</button>
                <button type="button" className="btn btn-ghost" onClick={() => { setDraftBase("http://localhost:10000"); }}>Use local laptop</button>
                <button type="submit" className="btn btn-primary"><Check size={15} /> Save and reconnect</button>
              </div>
            </form>
          </section>
        </div>
      )}
    </main>
  );
}