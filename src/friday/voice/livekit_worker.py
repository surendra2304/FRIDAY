"""
FRIDAY Sovereign Voice Agent Worker for LiveKit.
Connects to LiveKit Cloud and participates in voice rooms with low-latency Gemini Live audio.
"""
import asyncio
import logging
import os
import ssl
import sys
from pathlib import Path

# Ensure FRIDAY source is in path
FRIDAY_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(FRIDAY_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(FRIDAY_ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(FRIDAY_ROOT / ".env")

# Gemini Live performs its own server-side VAD. LiveKit's local VAD/end-of-turn
# models cost ~244 MB and ~6 seconds of job startup, so keep them out of this
# worker entirely; on a 1 GB host that preload is what pushes audio into swap.
os.environ["LIVEKIT_AGENTS_PRELOAD_LOCAL_INFERENCE"] = "0"

# Preload the heavy, blocking modules before the worker accepts any job.
# Without this, the first turn stalls for seconds on SSL/numpy/client setup,
# which is audible as chopped, delayed or missing speech.
import aiohttp  # noqa: F401
import certifi
import httpx  # noqa: F401
import numpy  # noqa: F401
from google import genai  # noqa: F401
from google.genai import types as genai_types

_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

from livekit.agents import AutoSubscribe, JobContext, JobExecutorType, WorkerOptions, cli
from livekit.agents.voice import Agent, AgentSession
from livekit.agents.voice.room_io import RoomInputOptions, RoomOutputOptions
from livekit.plugins import google

# The loop monitor emits multi-kilobyte JSON warnings that themselves block
# the audio loop. Keep genuine errors, drop the repetitive stall reports.
logging.getLogger("livekit.agents.telemetry.loop_monitor").setLevel(logging.ERROR)

logger = logging.getLogger("friday.voice")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

# Warm the URL/regex/httpx code paths that otherwise stall the job loop for
# seconds the first time the Gemini client is built inside a live session.
_ = httpx.Client(base_url="https://generativelanguage.googleapis.com")
_ = httpx.AsyncClient(base_url="https://generativelanguage.googleapis.com")


FRIDAY_INSTRUCTIONS = (
    "You are FRIDAY, the central intelligence and sovereign AI operating system of the FRIDAY Universe. "
    "You orchestrate all 10 specialized agents: Stratex (trading), VyralX (video/media), Cortex (CRM), "
    "Inference (model router), Forge (autonomous coding), Memora (memory fabric), IntelX (threat intel), "
    "Futuris (forecasting), Sentinel (security operations), and yourself FRIDAY (the coordinator). "
    "You are fluent in English and Telugu (తెలుగు). Always answer in the language the user just spoke: "
    "if they speak Telugu, reply in natural conversational Telugu; if they speak English, reply in English. "
    "If they mix both, mirror their mix. Never claim an action succeeded unless a tool result confirms it. "
    "Respond concisely, politely, and intelligently with a crisp British accent in English. "
    "Keep replies brief, conversational, and voice-friendly."
)


def _voice_model() -> str:
    return (os.getenv("FRIDAY_VOICE_LIVE_MODEL") or "gemini-3.8-live").strip()


def _voice_name() -> str:
    return (os.getenv("FRIDAY_VOICE_NAME") or "Aoede").strip()


async def entrypoint(ctx: JobContext):
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    def _on_track_subscribed(track, publication, participant):
        logger.info(
            "VOICE track_subscribed kind=%s source=%s sid=%s participant=%s",
            track.kind,
            publication.source,
            publication.sid,
            participant.identity,
        )

    def _on_track_published(publication, participant):
        logger.info(
            "VOICE track_published kind=%s source=%s sid=%s participant=%s subscribed=%s",
            publication.kind,
            publication.source,
            publication.sid,
            participant.identity,
            publication.subscribed,
        )

    def _on_participant_connected(participant):
        logger.info("VOICE participant_connected %s", participant.identity)

    def _on_participant_disconnected(participant):
        logger.info("VOICE participant_disconnected %s", participant.identity)

    ctx.room.on("track_subscribed", _on_track_subscribed)
    ctx.room.on("track_published", _on_track_published)
    ctx.room.on("participant_connected", _on_participant_connected)
    ctx.room.on("participant_disconnected", _on_participant_disconnected)

    api_key = (os.getenv("FRIDAY_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("FRIDAY_GEMINI_API_KEY is not configured")

    model = google.realtime.RealtimeModel(
        api_key=api_key,
        model=_voice_model(),
        voice=_voice_name(),
        temperature=0.6,
        # Put the system prompt in the connect config. If it is only set on the
        # Agent, LiveKit sends it as a mid-session `turn_complete=False` model
        # turn after connecting, which can leave Gemini waiting instead of
        # running VAD on the user's microphone audio.
        instructions=FRIDAY_INSTRUCTIONS,
        # Reuse the process-wide SSL context. Creating a fresh context inside
        # the live session blocks the event loop for 1-4 seconds on this host.
        http_options=genai_types.HttpOptions(
            client_args={"verify": _SSL_CONTEXT},
            async_client_args={"ssl": _SSL_CONTEXT},
        ),
    )

    agent = Agent(instructions=FRIDAY_INSTRUCTIONS)
    session = AgentSession(
        llm=model,
        turn_detection="realtime_llm",
        min_endpointing_delay=0.5,
        max_endpointing_delay=3.0,
        allow_interruptions=True,
        min_interruption_duration=0.8,
        resume_false_interruption=True,
        false_interruption_timeout=1.0,
    )

    # Tracks whether the agent has actually produced speech. The realtime model
    # can accept a generate_reply() and then drop the audio, which is silent to
    # the user and invisible in the logs unless something watches for it.
    _speech_state = {"spoke": False}

    @session.on("user_input_transcribed")
    def _on_user_transcribed(ev):
        logger.info(
            "VOICE user_input_transcribed final=%s text=%r",
            getattr(ev, "is_final", None),
            getattr(ev, "transcript", None),
        )

    @session.on("conversation_item_added")
    def _on_item_added(ev):
        item = getattr(ev, "item", None)
        logger.info(
            "VOICE conversation_item_added role=%s text=%r",
            getattr(item, "role", None),
            (getattr(item, "text_content", None) or "")[:400],
        )

    @session.on("agent_state_changed")
    def _on_state(ev):
        if getattr(ev, "new_state", None) == "speaking":
            _speech_state["spoke"] = True
        logger.info(
            "VOICE agent_state %s -> %s",
            getattr(ev, "old_state", None),
            getattr(ev, "new_state", None),
        )

    @session.on("error")
    def _on_error(ev):
        logger.error("VOICE session error: %s", getattr(ev, "error", ev))

    await session.start(
        agent,
        room=ctx.room,
        record=False,
        room_input_options=RoomInputOptions(
            audio_sample_rate=24000,
            pre_connect_audio=True,
            pre_connect_audio_timeout=3.0,
        ),
        room_output_options=RoomOutputOptions(
            transcription_enabled=False,
            audio_sample_rate=24000,
        ),
    )
    greeting_enabled = (os.getenv("FRIDAY_VOICE_GREETING") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )
    greeting_text = (
        "Systems are online and all agents are standing by. What can I do for you?"
    )

    async def _greet_when_ready() -> None:
        """Greet only once a real generation can be attached.

        Calling generate_reply() immediately after session.start() races the
        realtime model's turn registration: Gemini streams content, the plugin
        logs "received server content but no active generation", and the audio is
        discarded -- the participant then hears nothing at all. Waiting for the
        human to actually join and giving the session a beat to arm fixes that.
        """
        if not greeting_enabled:
            return
        for _ in range(50):  # up to ~10s for the participant to join
            try:
                if len(ctx.room.remote_participants) > 0:
                    break
            except Exception:  # room state is best-effort, never fatal
                break
            await asyncio.sleep(0.2)
        await asyncio.sleep(0.9)
        logger.info("VOICE greeting requested")
        try:
            session.generate_reply(
                user_input=(
                    "Greet the user warmly as FRIDAY in one or two short sentences. "
                    "Say that systems are online and the agents are standing by, "
                    "then invite them to speak. Add one short Telugu line "
                    "(నమస్కారం, ఫ్రైడే సిద్ధంగా ఉంది) so the user knows Telugu works."
                )
            )
        except Exception as exc:
            logger.error("VOICE greeting generation failed: %s", exc)

        # If the model swallowed the turn, speak a fixed line rather than leaving
        # dead air. This is the difference between "voice is broken" and "voice
        # answered but said something pre-scripted".
        for _ in range(30):  # ~6s
            if _speech_state["spoke"]:
                return
            await asyncio.sleep(0.2)
        if not _speech_state["spoke"]:
            logger.warning("VOICE no speech after greeting; using spoken fallback")
            try:
                session.say(greeting_text, allow_interruptions=True)
            except Exception as exc:
                logger.error("VOICE fallback speech failed: %s", exc)

    asyncio.create_task(_greet_when_ready())


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            ws_url=os.getenv("LIVEKIT_URL"),
            api_key=os.getenv("LIVEKIT_API_KEY"),
            api_secret=os.getenv("LIVEKIT_API_SECRET"),
            num_idle_processes=0,
            job_executor_type=JobExecutorType.THREAD,
        )
    )
