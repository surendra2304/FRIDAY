import asyncio
import logging
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from friday.agent.agent import FridayAgent
from friday.cli.auth import CLIAuthorizer
from friday.core.config import get_settings
from friday.core.logging import get_logger

logger = get_logger("api.server")

app = FastAPI(title="FRIDAY UI Server")

# Allow Next.js frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings = get_settings()

# We initialize a global agent for the server
agent = FridayAgent(
    settings=settings,
    authorizer=CLIAuthorizer(),  # Assuming trusted local network UI
)


class CommandRequest(BaseModel):
    command: str


@app.post("/api/command")
async def execute_command(req: CommandRequest) -> dict[str, Any]:
    """Execute a text command and return the response."""
    # Run sync process_message in an executor to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    
    # We use run_in_executor for process_message because it's synchronous but does LLM calls
    response = await loop.run_in_executor(None, agent.process_message, req.command)
    return {"reply": response.content, "metadata": response.metadata}


@app.websocket("/api/ws/voice")
async def voice_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for bidirectional audio and control.
    Currently, this acts as an echo/control endpoint. For a full Gemini Live Realtime session,
    it would pipe audio bytes to gemini_live_session.py.
    """
    await websocket.accept()
    logger.info("WebSocket connected from UI")
    try:
        while True:
            data = await websocket.receive_json()
            event_type = data.get("type")
            if event_type == "gesture":
                gesture = data.get("gesture")
                logger.info(f"Received gesture: {gesture}")
                # We could dispatch this gesture as a command to FridayAgent
                # E.g., if "swipe_left", trigger next window etc.
                await websocket.send_json({"type": "status", "message": f"Processed gesture {gesture}"})
            elif event_type == "audio":
                # placeholder for audio routing
                pass
            else:
                logger.warning(f"Unknown WS event type: {event_type}")

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
