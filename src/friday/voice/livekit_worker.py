"""
FRIDAY Sovereign Voice Agent Worker for LiveKit.
Connects to LiveKit Cloud and participates in voice rooms with low-latency Gemini Live audio.
"""
import os
import sys
from pathlib import Path

# Ensure FRIDAY source is in path
FRIDAY_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(FRIDAY_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(FRIDAY_ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(FRIDAY_ROOT / ".env")

from livekit.agents import AutoSubscribe, JobContext, JobExecutorType, WorkerOptions, cli
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import google

FRIDAY_INSTRUCTIONS = (
    "You are FRIDAY, the central intelligence and sovereign AI operating system of the FRIDAY Universe. "
    "You orchestrate all 10 specialized agents: Stratex (trading), VyralX (video/media), Cortex (CRM), "
    "Inference (model router), Forge (autonomous coding), Memora (memory fabric), IntelX (threat intel), "
    "Futuris (forecasting), Sentinel (security operations), and yourself FRIDAY (the coordinator). "
    "Respond concisely, politely, and intelligently with a crisp British accent. "
    "Keep replies brief, conversational, and voice-friendly."
)

async def entrypoint(ctx: JobContext):
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    api_key = os.getenv("FRIDAY_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
    model = google.realtime.RealtimeModel(
        api_key=api_key,
        voice="Aoede",
    )

    agent = Agent(instructions=FRIDAY_INSTRUCTIONS)
    session = AgentSession(llm=model)

    await session.start(agent, room=ctx.room)
    session.generate_reply(
        user_input="Greet the user warmly as FRIDAY. State that systems are online, all 10 agents in the FRIDAY Universe are active, and ask how you can help."
    )

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
