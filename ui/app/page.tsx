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
  Mic,
  MessageSquareText,
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
    // The dashboard does not ask the owner to paste the server key. Mint a
    // short-lived same-origin control session and retry once.
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

function TinyChart({ values, color }: { values: number[]; color: string }) {
  const points = useMemo(() => {
    if (values.length < 2) return "";
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = Math.max(max - min, 1);
    return values.map((value, index) => {
      const x = (index / (values.length - 1)) * 100;
      const y = 29 - ((value - min) / span) * 23;
      return `${x},${y}`;
    }).join(" ");
  }, [values]);

  return (
    <svg className="tiny-chart" viewBox="0 0 100 32" role="img" aria-label="Recent measured samples">
      <path d="M0 30 H100" className="chart-baseline" />
      {points && <polyline points={points} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />}
      {points && <circle cx={points.split(" ").at(-1)?.split(",")[0]} cy={points.split(" ").at(-1)?.split(",")[1]} r="2.2" fill={color} />}
    </svg>
  );
}

function LiveKitVoicePanel() {
  const [status, setStatus] = useState<"idle" | "connecting" | "connected" | "error">("idle");
  const [message, setMessage] = useState("LiveKit voice is disconnected.");
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
      setMessage("LiveKit voice is disconnected.");
      return;
    }

    setStatus("connecting");
    setMessage("Requesting a secure voice room…");
    setAudioBlocked(false);
    setAgentAudio(false);

    // Create the room and unlock its audio context *inside* the click gesture,
    // before any network await can consume the browser's transient activation.
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
        setMessage("FRIDAY joined the room. Speak now — she can hear you.");
      });

      room.on(RoomEvent.TrackUnsubscribed, (track) => {
        track.detach().forEach((element) => element.remove());
      });

      room.on(RoomEvent.AudioPlaybackStatusChanged, () => {
        setAudioBlocked(!room.canPlaybackAudio);
      });

      room.on(RoomEvent.Disconnected, () => {
        clearAudioElements();
        setAgentAudio(false);
        setStatus("idle");
        setMessage("LiveKit voice is disconnected.");
      });

      await room.connect(body.server_url, body.token);
      await room.startAudio().catch(() => setAudioBlocked(true));

      roomRef.current = room;

      try {
        await room.localParticipant.setMicrophoneEnabled(true);
        setStatus("connected");
        setMessage(`Connected to room “${body.room}”. Microphone is live — say hello.`);
      } catch (micErr) {
        console.warn("Microphone access failed (e.g. side browser restricted):", micErr);
        setStatus("connected");
        setMessage(`Connected to room “${body.room}” (listening only — microphone was blocked).`);
      }
    } catch (error) {
      room.disconnect();
      roomRef.current = null;
      clearAudioElements();
      setStatus("error");
      setMessage(error instanceof Error ? error.message : "LiveKit connection failed.");
    }
  }

  async function enableAudio() {
    const room = roomRef.current;
    if (!room) return;
    try {
      await room.startAudio();
      setAudioBlocked(false);
    } catch (error) {
      console.warn("Audio unlock failed:", error);
      setAudioBlocked(true);
    }
  }

  return (
    <article className="surface voice-surface" aria-label="LiveKit voice">
      <div className="section-heading">
        <div><div className="section-kicker">REALTIME VOICE</div><h2>LiveKit room</h2></div>
        <Radio size={17} className={status === "connected" ? "heading-icon live" : "heading-icon"} />
      </div>
      <p className="surface-copy">{message}</p>
      <div className="voice-actions">
        <button className="small-action" onClick={() => void toggleVoice()} disabled={status === "connecting"}>
          {status === "connecting" ? <LoaderCircle size={14} className="spin" /> : <Mic size={14} />}
          {status === "connected" ? "Leave room" : "Join voice"}
        </button>
        {status === "connected" && audioBlocked && (
          <button className="small-action" onClick={() => void enableAudio()}>
            <Volume2 size={14} /> Enable audio
          </button>
        )}
      </div>
      {status === "connected" && agentAudio && !audioBlocked && (
        <p className="voice-live-note">Agent audio track is live.</p>
      )}
      {status === "error" && <div className="inline-error"><AlertCircle size={15} />{message}</div>}
    </article>
  );
}

export default function FridayCommandCenter() {
  const [fleet, setFleet] = useState<FleetSnapshot | null>(null);
  const [telemetry, setTelemetry] = useState<HostTelemetry | null>(null);
  const [autonomy, setAutonomy] = useState<AutonomySnapshot | null>(null);
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [fleetError, setFleetError] = useState("");
  const [telemetryError, setTelemetryError] = useState("");
  const [command, setCommand] = useState("");
  const [reply, setReply] = useState("");
  const [commandError, setCommandError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [draftBase, setDraftBase] = useState(process.env.NEXT_PUBLIC_FRIDAY_API_URL?.trim() ?? "");
  const [draftToken, setDraftToken] = useState("");
  const [connected, setConnected] = useState<"checking" | "online" | "offline">("checking");
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [cpuHistory, setCpuHistory] = useState<number[]>([]);
  const [ramHistory, setRamHistory] = useState<number[]>([]);
  const [agentActivity, setAgentActivity] = useState<AutonomySnapshot | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [agentDirective, setAgentDirective] = useState("");
  const [agentResult, setAgentResult] = useState("");
  const [agentBusy, setAgentBusy] = useState(false);
  const [controlReady, setControlReady] = useState(false);
  const [now, setNow] = useState(new Date());
  const [hydrated, setHydrated] = useState(false);

  const refresh = useCallback(async (manual = false) => {
    if (manual) setRefreshing(true);
    const [fleetResult, telemetryResult, autonomyResult, healthResult] = await Promise.allSettled([
      requestJson<FleetSnapshot>("/api/agents/status"),
      requestJson<HostTelemetry>("/api/system_telemetry"),
      requestJson<AutonomySnapshot>("/api/autonomous/status"),
      requestJson<Record<string, unknown>>("/api/health"),
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
        setCpuHistory((current) => [...current, data.cpu_percent!].slice(-32));
      }
      if (data.status === "ok" && typeof data.ram_percent === "number") {
        setRamHistory((current) => [...current, data.ram_percent!].slice(-32));
      }
      setTelemetryError(data.status === "ok" ? "" : data.error ?? "Host telemetry unavailable");
    } else {
      setTelemetry(null);
      setTelemetryError(telemetryResult.reason instanceof Error ? telemetryResult.reason.message : "Host telemetry unavailable");
    }
    if (autonomyResult.status === "fulfilled") setAutonomy(autonomyResult.value);
    if (healthResult.status === "fulfilled") setHealth(healthResult.value);
    if (manual) setRefreshing(false);
  }, []);

  useEffect(() => {
    setHydrated(true);
    // First-run defaults: never make the owner re-enter the production URL or key.
    if (typeof window !== "undefined") {
      const base = window.localStorage.getItem(API_BASE_SESSION_KEY);
      if (!base || /localhost:10000|localhost:9000/.test(base)) {
        window.localStorage.setItem(API_BASE_SESSION_KEY, "https://friday-universe.duckdns.org");
      }
      if (!window.localStorage.getItem(API_TOKEN_SESSION_KEY)) {
        // The control session is the dashboard's credential; the server key is
        // never shipped in the client bundle.
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
      setAgentActivity(data);
    } catch {
      // ignore
    }
  }

  function openSettings() {
    setDraftBase(apiBase());
    setDraftToken(window.localStorage.getItem(API_TOKEN_SESSION_KEY) ?? "");
    setShowSettings(true);
  }

  const agents = fleet?.agents ?? [];
  const onlineCount = agents.filter((agent) => agent.status?.toUpperCase() === "ONLINE").length;
  const selected = agents.find((agent) => agent.id === selectedAgent) ?? null;
  const displayNow = hydrated ? now : new Date(0);
  const hostLabel = !hydrated
    ? "Service host"
    : ["localhost", "127.0.0.1"].includes(window.location.hostname)
      ? "Connected laptop"
      : "FRIDAY service host";

  async function submitCommand(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const clean = command.trim();
    if (!clean || busy) return;
    setBusy(true);
    setCommandError("");
    setReply("");
    try {
      const result = await requestJson<{ reply?: string; metadata?: Record<string, unknown> }>("/api/command", {
        method: "POST",
        body: JSON.stringify({ command: clean }),
      });
      const answer = result.reply || "FRIDAY returned no reply text.";
      setReply(answer);
      setActivity((current) => [{ id: Date.now(), at: new Date().toISOString(), command: clean, reply: answer, success: true }, ...current].slice(0, 12));
      setCommand("");
      void refresh();
    } catch (error) {
      const message = error instanceof Error ? error.message : "The command could not be sent.";
      setCommandError(message);
      setActivity((current) => [{ id: Date.now(), at: new Date().toISOString(), command: clean, reply: message, success: false }, ...current].slice(0, 12));
    } finally {
      setBusy(false);
    }
  }

  async function cancelTasks() {
    if (busy) return;
    setBusy(true);
    setCommandError("");
    try {
      const result = await requestJson<{ status?: string; cancelled_count?: number }>("/api/tasks/cancel-all", { method: "POST" });
      const answer = result.status === "cancelled"
        ? `Cancel request returned: ${result.cancelled_count ?? 0} task(s) cancelled.`
        : `Cancel request returned: ${result.status ?? "unknown status"}.`;
      setReply(answer);
    } catch (error) {
      setCommandError(error instanceof Error ? error.message : "Could not send cancel request.");
    } finally {
      setBusy(false);
    }
  }

  async function toggleAutonomy() {
    if (busy) return;
    setBusy(true);
    setCommandError("");
    try {
      const result = await requestJson<{ status?: string; autonomous_mode?: boolean }>("/api/autonomous/toggle", { method: "POST" });
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
    if (!clean || agentBusy || !selected) return;
    setAgentBusy(true);
    setAgentResult("");
    setCommandError("");
    try {
      const result = await requestJson<{ reply?: string; metadata?: Record<string, unknown> }>(
        `/api/agents/${encodeURIComponent(selected.id)}/task`,
        { method: "POST", body: JSON.stringify({ directive: clean }) },
      );
      const answer = result.reply || `${selected.name} returned no reply text.`;
      setAgentResult(answer);
      setActivity((current) => [{ id: Date.now(), at: new Date().toISOString(), command: `@${selected.id} ${clean}`, reply: answer, success: true }, ...current].slice(0, 12));
      setAgentDirective("");
      void refresh();
    } catch (error) {
      const message = error instanceof Error ? error.message : "The agent task could not be sent.";
      setAgentResult(message);
      setActivity((current) => [{ id: Date.now(), at: new Date().toISOString(), command: `@${selected.id} ${clean}`, reply: message, success: false }, ...current].slice(0, 12));
    } finally {
      setAgentBusy(false);
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

  function saveConnection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanBase = draftBase.trim().replace(/\/$/, "");
    if (cleanBase) window.localStorage.setItem(API_BASE_SESSION_KEY, cleanBase);
    else window.localStorage.removeItem(API_BASE_SESSION_KEY);
    if (draftToken.trim()) window.localStorage.setItem(API_TOKEN_SESSION_KEY, draftToken.trim());
    else window.localStorage.removeItem(API_TOKEN_SESSION_KEY);
    setShowSettings(false);
    setConnected("checking");
    void refresh(true);
  }

  return (
    <main className="friday-shell">
      <aside className="sidebar">
        <a className="brand" href="#home" aria-label="FRIDAY home">
          <span className="brand-mark"><AudioLines size={19} strokeWidth={2.1} /></span>
          <span className="brand-copy"><strong>FRIDAY</strong><small>UNIVERSE CONTROL</small></span>
        </a>
        <div className="sidebar-label">WORKSPACE</div>
        <nav className="side-nav" aria-label="Main navigation">
          <a className="nav-link active" href="#home"><Command size={17} />Command center</a>
          <a className="nav-link" href="#fleet"><Globe2 size={17} />Agent network<span className="nav-count">{fleet?.agent_count ?? "—"}</span></a>
          <a className="nav-link" href="#host"><Monitor size={17} />Host telemetry</a>
          <a className="nav-link" href="#activity"><Activity size={17} />This session<span className="nav-count">{activity.length}</span></a>
        </nav>
        <div className="sidebar-spacer" />
        <div className="sidebar-network">
          <div className="network-top"><span className={`status-dot ${connected}`} />Network check</div>
          <p>{connected === "online" ? "FRIDAY API responded" : connected === "offline" ? "FRIDAY API unavailable" : "Checking service…"}</p>
            <button className="text-button" onClick={openSettings}><Settings2 size={14} /> Connection settings</button>
        </div>
        <div className="sidebar-footer"><span className="user-avatar">S</span><span><strong>Surendra</strong><small>Owner</small></span><ChevronDown size={15} /></div>
      </aside>

      <section className="main-area" id="home">
        <header className="topbar">
          <div className="breadcrumb"><span>Workspace</span><span className="slash">/</span><strong>Command center</strong></div>
          <div className="top-actions">
            <div className="clock"><Clock3 size={15} /><span>{hydrated ? new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(displayNow) : "—:—"}</span></div>
            <button className="icon-button" title="Refresh live data" onClick={() => void refresh(true)} disabled={refreshing}>
              <RefreshCw size={16} className={refreshing ? "spin" : ""} />
            </button>
            <button className="top-key" onClick={openSettings}><KeyRound size={14} /> Connect</button>
          </div>
        </header>

        <div className="page-content">
          <section className="welcome-row">
            <div>
              <div className="eyebrow"><span className="eyebrow-line" />PERSONAL ASSISTANT · LIVE CONSOLE</div>
              <h1>Good {displayNow.getHours() < 12 ? "morning" : displayNow.getHours() < 18 ? "afternoon" : "evening"}, Surendra<span className="title-period">.</span></h1>
              <p className="welcome-subtitle">Your workspace at a glance. Ask FRIDAY to handle a task, or inspect the connected agent network.</p>
            </div>
            <div className="live-pill"><span className={`status-dot ${connected}`} />{connected === "online" ? "API responding" : connected === "offline" ? "API unavailable" : "Connecting"}</div>
          </section>

          <section className="command-panel" aria-label="Ask FRIDAY">
            <div className="command-panel-top">
              <div className="assistant-avatar"><AudioLines size={20} /></div>
              <div><strong>Talk to FRIDAY</strong><span>Commands run on the connected FRIDAY host.</span></div>
              <span className={`panel-tag${controlReady ? " granted" : ""}`}>
                <LockKeyhole size={12} />
                {controlReady ? "Control access granted" : "Requesting control access…"}
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
              <div className="composer-bottom">
                <span><kbd>Enter</kbd> send <span className="composer-separator">·</span> <kbd>Shift + Enter</kbd> new line</span>
                <button className="send-button" type="submit" disabled={busy || !command.trim()}>
                  {busy ? <LoaderCircle size={16} className="spin" /> : <Send size={15} />}
                  {busy ? "Working" : "Send"}
                </button>
              </div>
            </form>
            {commandError && <div className="inline-error"><AlertCircle size={15} />{commandError}{/key|required|401|403|503/i.test(commandError) && <button onClick={openSettings}>Set connection key</button>}</div>}
            {reply && <div className="reply-card"><div className="reply-label"><span className="reply-dot" />FRIDAY RESPONSE</div><p>{reply}</p></div>}
          </section>

          <section className="metrics-grid" id="host">
            <article className="metric-card">
              <div className="metric-heading"><span className="metric-icon cpu"><Cpu size={17} /></span><span>CPU LOAD</span><span className="metric-host">{hostLabel}</span></div>
              {telemetry?.status === "ok" && typeof telemetry.cpu_percent === "number" ? <>
                <div className="metric-value">{telemetry.cpu_percent}<small>%</small></div>
                <div className="metric-bottom"><span>{telemetry.cpu_cores ?? "—"} logical cores</span><TinyChart values={cpuHistory} color="#8de6cf" /></div>
              </> : <MetricUnavailable message={telemetryError || "Waiting for host telemetry"} />}
            </article>
            <article className="metric-card">
              <div className="metric-heading"><span className="metric-icon memory"><Activity size={17} /></span><span>MEMORY</span><span className="metric-host">{hostLabel}</span></div>
              {telemetry?.status === "ok" && typeof telemetry.ram_percent === "number" ? <>
                <div className="metric-value">{telemetry.ram_percent}<small>%</small></div>
                <div className="metric-bottom"><span>{telemetry.ram_used_gb ?? "—"} / {telemetry.ram_total_gb ?? "—"} GB used</span><TinyChart values={ramHistory} color="#b9a6ff" /></div>
              </> : <MetricUnavailable message={telemetryError || "Waiting for host telemetry"} />}
            </article>
            <article className="metric-card fleet-metric">
              <div className="metric-heading"><span className="metric-icon fleet"><Globe2 size={17} /></span><span>AGENT REACHABILITY</span><span className={`metric-state ${statusTone(fleet?.status)}`}>{fleet?.status ?? "UNKNOWN"}</span></div>
              {fleet ? <>
                <div className="metric-value">{onlineCount}<small> / {fleet.agent_count ?? agents.length}</small></div>
                <div className="metric-bottom"><span>HTTP health responses only</span><a href="#fleet">Inspect fleet <ArrowUpRight size={13} /></a></div>
              </> : <MetricUnavailable message={fleetError || "Waiting for network check"} />}
            </article>
            <article className="metric-card autonomy-metric">
              <div className="metric-heading"><span className="metric-icon autonomy"><Zap size={17} /></span><span>AUTONOMOUS MODE</span><span className={`metric-state ${autonomy?.autonomous_mode ? "good" : "muted"}`}>{autonomy ? autonomy.autonomous_mode ? "ON" : "OFF" : "UNKNOWN"}</span></div>
              <div className="autonomy-row"><div><strong>{autonomy?.autonomous_mode ? "Enabled" : autonomy ? "Manual control" : "Status unavailable"}</strong><span>{autonomy?.history_count ?? "—"} recorded actions</span></div><button className="small-action" onClick={() => void toggleAutonomy()} disabled={busy || !autonomy} title="Toggle autonomy on the connected host">Toggle</button></div>
            </article>
          </section>

          <section className="apartment-surface surface" id="apartment">
            <div className="section-heading">
              <div><div className="section-kicker">LIVE FLEET</div><h2>Agent apartment</h2></div>
              <div className="section-heading-right"><span className="updated-at">{agentActivity?.active_agent ? `Active: ${agentActivity.active_agent}` : "All agents standing by"}</span></div>
            </div>
            <div className="apartment-grid">
              {agents.map((agent) => {
                const last = agentActivity?.recent_actions?.find((a) => a.target?.toUpperCase() === agent.name?.toUpperCase());
                const isActive = agentActivity?.active_agent?.toLowerCase() === agent.id;
                return (
                  <div key={agent.id} className={`apartment-room ${isActive ? "active" : ""} ${statusTone(agent.status)}`}>
                    <div className="apartment-room-head">
                      <span className={`status-dot ${statusTone(agent.status) === "good" ? "online" : statusTone(agent.status) === "bad" ? "offline" : "checking"}`} />
                      <strong>{agent.name}</strong>
                      <span className="apartment-room-id">{agent.id}</span>
                    </div>
                    <div className="apartment-room-status">{agent.status} · {typeof agent.latency_ms === "number" ? `${Math.round(agent.latency_ms)} ms` : "—"}</div>
                    <div className="apartment-room-task">{last ? `${last.directive}` : "Idle — awaiting directive"}</div>
                    {last && <div className={`apartment-room-result ${last.success ? "good" : "bad"}`}>{last.success ? "✓" : "✗"} {String(last.result ?? "").slice(0, 80)}</div>}
                  </div>
                );
              })}
            </div>
          </section>
          <section className="workspace-grid">
            <article className="surface fleet-surface" id="fleet">
              <div className="section-heading">
                <div><div className="section-kicker">CONNECTED SERVICES</div><h2>Agent network</h2></div>
                <div className="section-heading-right"><span className="updated-at">{fleet?.timestamp ? `Checked ${formatTime(fleet.timestamp)}` : "No check yet"}</span><button className="subtle-button" onClick={() => void refresh(true)} disabled={refreshing}><RefreshCw size={14} className={refreshing ? "spin" : ""} />Refresh</button></div>
              </div>
              {fleetError ? <ErrorState title="Could not load the agent network" detail={fleetError} action={() => void refresh(true)} /> : !fleet ? <LoadingGrid /> : agents.length === 0 ? <EmptyState title="No agent status returned" detail="The FRIDAY API responded, but it did not return any agents." /> : <>
                <div className="agent-grid">
                  {agents.map((agent) => <button key={agent.id} className={`agent-card ${selectedAgent === agent.id ? "selected" : ""}`} onClick={() => setSelectedAgent(selectedAgent === agent.id ? null : agent.id)}>
                    <div className="agent-card-top"><span className={`agent-status ${statusTone(agent.status)}`}><span className="status-dot" />{agent.status}</span><ArrowUpRight size={15} className="agent-open-icon" /></div>
                    <div className="agent-name">{agent.name}</div>
                    <div className="agent-role">{agent.role || "Connected service"}</div>
                    <div className="agent-card-foot"><span>{typeof agent.latency_ms === "number" ? `${Math.round(agent.latency_ms)} ms` : "Latency —"}</span><span className="agent-id">{agent.id}</span></div>
                  </button>)}
                </div>
                <div className="fleet-disclaimer"><ShieldCheck size={15} /><span>{fleet.note || "Reachability does not prove task execution, shared memory, or event delivery."}</span></div>
              </>}
              {selected && <div className="agent-detail">
                <div className="agent-detail-title"><div><span className="section-kicker">SERVICE DETAIL</span><h3>{selected.name}</h3></div><button className="icon-button compact" onClick={() => setSelectedAgent(null)} aria-label="Close agent detail"><X size={15} /></button></div>
                <p>{selected.details || selected.desc || "No additional description was returned by the service."}</p>
                <div className="agent-detail-meta"><span>Role <strong>{selected.role || "—"}</strong></span><span>Endpoint <strong>{selected.endpoint || "not exposed"}</strong></span><span>Latency <strong>{typeof selected.latency_ms === "number" ? `${Math.round(selected.latency_ms)} ms` : "not reported"}</strong></span></div>
                <div className="agent-detail-actions"><a className="subtle-button" href={`https://friday-universe.duckdns.org/${selected.id}`} target="_blank" rel="noreferrer"><ArrowUpRight size={14} />Open {selected.name} site</a></div>
                <form className="agent-task-form" onSubmit={runAgentTask}>
                  <label htmlFor="agent-directive">Send {selected.name} a task</label>
                  <div className="agent-task-row">
                    <input
                      id="agent-directive"
                      value={agentDirective}
                      onChange={(event) => setAgentDirective(event.target.value)}
                      placeholder={`e.g. ${selected.id === "forge" ? "run the test suite and report failures" : selected.id === "intelx" ? "research this week's macro news" : "report status and current workload"}`}
                      disabled={agentBusy}
                    />
                    <button className="send-button" type="submit" disabled={agentBusy || !agentDirective.trim()}>
                      {agentBusy ? <LoaderCircle size={15} className="spin" /> : <Send size={14} />}
                      {agentBusy ? "Dispatching" : "Dispatch"}
                    </button>
                  </div>
                </form>
                {agentResult && <div className="reply-card compact"><div className="reply-label"><span className="reply-dot" />{selected.name.toUpperCase()} RESPONSE</div><p>{agentResult}</p></div>}
              </div>}
            </article>

            <article className="surface activity-surface" id="activity">
              <div className="section-heading">
                <div><div className="section-kicker">CURRENT BROWSER SESSION</div><h2>Recent commands</h2></div>
                <span className="activity-count">{activity.length}</span>
              </div>
              {activity.length === 0 ? <div className="activity-empty"><div className="activity-empty-icon"><MessageSquareText size={18} /></div><strong>No commands yet</strong><p>Commands you send here will appear in this session log.</p></div> : <div className="activity-list">
                {activity.map((item) => <div className="activity-item" key={item.id}>
                  <span className={`activity-result ${item.success ? "good" : "bad"}`}>{item.success ? <Check size={13} /> : <AlertCircle size={13} />}</span>
                  <div className="activity-copy"><strong>{item.command}</strong><p>{item.reply}</p><time>{formatTime(item.at)}</time></div>
                </div>)}
              </div>}
              <div className="activity-footer"><span><Clock3 size={13} />Local to this browser tab</span><button className="text-button" onClick={() => setActivity([])} disabled={activity.length === 0}>Clear</button></div>
            </article>
          </section>

          <section className="bottom-grid">
            <LiveKitVoicePanel />
            <article className="surface host-surface">
              <div className="section-heading"><div><div className="section-kicker">RUNTIME CONTEXT</div><h2>Connected host</h2></div><Monitor size={17} className="heading-icon" /></div>
              <div className="host-info-row"><span>Host system</span><strong>{telemetry?.os || (telemetryError ? "Unavailable" : "Waiting for telemetry")}</strong></div>
              <div className="host-info-row"><span>Operator</span><strong>{telemetry?.operator || "Not reported"}</strong></div>
              <div className="host-info-row"><span>Host sample</span><strong>{formatTime(telemetry?.timestamp)}</strong></div>
              <div className="host-info-row"><span>Health response</span><strong className={`metric-state ${statusTone(String(health?.status ?? ""))}`}>{String(health?.status ?? "UNKNOWN")}</strong></div>
              <div className="host-note"><AlertCircle size={14} />Telemetry describes the machine running the FRIDAY API. When connected to Render, this is the cloud host—not this laptop.</div>
            </article>
            <article className="surface actions-surface">
              <div className="section-heading"><div><div className="section-kicker">CONTROL</div><h2>Task controls</h2></div><Radio size={17} className="heading-icon" /></div>
              <p className="actions-copy">These controls call the connected FRIDAY API. The dashboard mints a short-lived control session automatically; no key needs to be pasted.</p>
              <div className="action-buttons"><button className="danger-button" onClick={() => void cancelTasks()} disabled={busy}><Square size={14} />Cancel active tasks</button><button className="subtle-button" onClick={() => void triggerRepair()} disabled={busy}><Zap size={14} />Self-repair sweep</button><button className="subtle-button" onClick={openSettings}><Settings2 size={14} />Connection settings</button></div>
              <div className="control-foot"><LockKeyhole size={13} />{controlReady || autonomy ? "Control session active" : "Control session unavailable"} · expires automatically</div>
            </article>
          </section>

          <footer className="page-footer"><span>FRIDAY · PERSONAL AI CONTROL ROOM</span><span>Fleet sample: {fleet?.scope || "not available"}</span><a href="/api/health" target="_blank" rel="noreferrer">API health <ExternalLink size={12} /></a></footer>
        </div>
      </section>

      {showSettings && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowSettings(false); }}>
        <section className="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
          <div className="modal-heading"><div><span className="section-kicker">API CONNECTION</span><h2 id="settings-title">Connect to FRIDAY</h2></div><button className="icon-button compact" onClick={() => setShowSettings(false)} aria-label="Close settings"><X size={16} /></button></div>
          <p>Use your local FRIDAY API for laptop control, or enter a remote service URL. A remote control API key is required by the server. The key is held only for this browser tab.</p>
          <form onSubmit={saveConnection} className="settings-form">
            <label>FRIDAY API URL<input value={draftBase} onChange={(event) => setDraftBase(event.target.value)} placeholder="https://friday-universe.duckdns.org" inputMode="url" /></label>
            <label>Control API key <span className="optional-label">optional for localhost</span><input type="password" autoComplete="off" value={draftToken} onChange={(event) => setDraftToken(event.target.value)} placeholder="Paste key from your private service configuration" /></label>
            <div className="modal-warning"><LockKeyhole size={15} /><span>Never paste a key into a shared device. This UI does not send the key anywhere except the configured FRIDAY API.</span></div>
            <div className="modal-actions"><button type="button" className="subtle-button" onClick={() => { window.localStorage.removeItem(API_BASE_SESSION_KEY); window.localStorage.removeItem(API_TOKEN_SESSION_KEY); setDraftBase(apiBase()); setDraftToken(""); }}>Reset</button><button type="button" className="subtle-button" onClick={() => { setDraftBase("http://localhost:10000"); }}>Use local laptop</button><button type="submit" className="send-button"><Check size={15} />Save and reconnect</button></div>
          </form>
        </section>
      </div>}
    </main>
  );
}

function MetricUnavailable({ message }: { message: string }) {
  return <div className="metric-unavailable"><Circle size={14} />{message}</div>;
}

function ErrorState({ title, detail, action }: { title: string; detail: string; action: () => void }) {
  return <div className="state-block error-block"><AlertCircle size={18} /><div><strong>{title}</strong><p>{detail}</p></div><button className="subtle-button" onClick={action}>Retry</button></div>;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="state-block"><Globe2 size={18} /><div><strong>{title}</strong><p>{detail}</p></div></div>;
}

function LoadingGrid() {
  return <div className="agent-grid loading-grid" aria-label="Loading agent network">{Array.from({ length: 4 }).map((_, index) => <div className="agent-skeleton" key={index}><i /><i /><i /></div>)}</div>;
}
