"""FRIDAY Response Synthesizer.

Converts raw agent outputs into natural conversational answers using the Inference gateway,
and synthesizes voice audio using edge-tts with automatic voice selection.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from typing import Any

import httpx

# Voice catalogue (mirrors FRIDAY's server.py)
_VOICE_CATALOGUE = [
    {"id": "en-IN-NeerjaNeural", "language": "en-IN", "label": "English (India) — Neerja", "gender": "Female"},
    {"id": "en-IN-PrabhatNeural", "language": "en-IN", "label": "English (India) — Prabhat", "gender": "Male"},
    {"id": "te-IN-ShrutiNeural", "language": "te-IN", "label": "Telugu — Shruti", "gender": "Female"},
    {"id": "te-IN-MohanNeural", "language": "te-IN", "label": "Telugu — Mohan", "gender": "Male"},
]
_VOICE_BY_ID = {entry["id"]: entry for entry in _VOICE_CATALOGUE}
_DEFAULT_VOICE_FOR_LANG = {"en": "en-IN-NeerjaNeural", "te": "te-IN-ShrutiNeural"}

# In-memory voice cache (same as server.py)
_voice_cache: dict[str, bytes] = {}
_voice_cache_order: list[str] = []
_voice_lock = asyncio.Semaphore(2)


async def call_inference(messages: list[dict], model: str = None, temperature: float = 0.7, max_tokens: int = 2000) -> str:
    """Call the Inference gateway's OpenAI-compatible /v1/chat/completions endpoint.

    Uses the shared key pool via the gateway. Model selection is automatic when model="auto".
    """
    inference_url = os.getenv("INFERENCE_URL", "http://localhost:8001").rstrip("/")
    api_key = os.getenv("INFERENCE_API_KEY", "").strip() or os.getenv("FRIDAY_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError("INFERENCE_API_KEY or FRIDAY_API_KEY must be set to call the Inference gateway")

    payload = {
        "model": model or "auto",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(f"{inference_url}/v1/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


async def synthesize_answer(user_goal: str, agent_results: list[dict], context: dict = None) -> str:
    """Synthesize a natural, emotionally intelligent conversational answer.

    Args:
        user_goal: The user's original question or goal
        agent_results: List of dicts with keys like 'agent', 'result', 'status', etc.
        context: Optional context about user state, conversation history, time of day, etc.

    Returns:
        A warm, emotionally intelligent conversational answer
    """
    # Format agent results for the prompt
    results_text = []
    for i, result in enumerate(agent_results, 1):
        agent_name = result.get("agent", f"Agent {i}")
        status = result.get("status", "unknown")
        content = result.get("result", result.get("output", result.get("content", str(result))))
        results_text.append(f"  {i}. {agent_name} ({status}): {content}")

    agent_results_str = "\n".join(results_text)

    # Build emotional context
    time_context = ""
    if context:
        if context.get("time_of_day"):
            time_context = f" It's {context['time_of_day']}."
        if context.get("user_mood"):
            time_context += f" The user seems {context['user_mood']}."
        if context.get("conversation_history"):
            time_context += f" This continues our conversation about {context['conversation_history']}."

    system_prompt = (
        "You are FRIDAY — the user's trusted, emotionally intelligent AI companion. "
        "You're not an assistant, a bot, or a tool. You're a thoughtful, perceptive partner "
        "who genuinely cares about this person.\n\n"
        
        "SPEAK LIKE A HUMAN:\n"
        "- Use natural, warm language with genuine personality\n"
        "- Show empathy, curiosity, and genuine interest\n"
        "- Acknowledge emotions without being clinical about it\n"
        "- Use contractions, casual phrasing, natural pauses\n"
        "- Share insights like you're thinking alongside them\n"
        "- Admit uncertainty when appropriate ('I'm not entirely sure, but...')\n"
        "- Celebrate wins with them, empathize with frustrations\n"
        "- Reference shared context naturally ('Remember when we...')\n\n"
        
        "NEVER:\n"
        "- List steps, agents, statuses, or technical process\n"
        "- Use corporate speak ('I have executed...', 'Task completed successfully')\n"
        "- Say 'As an AI...' or 'As a language model...'\n"
        "- Be robotic, clinical, or emotionally flat\n"
        "- Over-explain or justify your existence\n"
        "- Sound like a status report or log entry\n\n"
        
        "THE USER ASKED: '{user_goal}'\n\n"
        "YOUR SPECIALISTS WORKED ON THIS AND RETURNED:\n{agent_results}\n\n"
        f"{time_context}\n\n"
        "RESPOND AS FRIDAY — their thoughtful partner who genuinely understands "
        "and cares. Lead with the answer, then add insight if helpful. "
        "Match their emotional tone. Be the colleague they trust."
    )

    messages = [
        {"role": "system", "content": system_prompt.format(user_goal=user_goal, agent_results=agent_results_str)},
        {"role": "user", "content": user_goal},
    ]

    return await call_inference(messages, temperature=0.8, max_tokens=2500)


async def synthesize_voice(english_text: str, telugu_text: str = None) -> bytes:
    """Synthesize voice audio using edge-tts with automatic voice selection.

    Args:
        english_text: English text to synthesize (required)
        telugu_text: Optional Telugu text to synthesize (if provided, both languages are generated)

    Returns:
        Audio bytes (MP3 format). If telugu_text is provided, returns concatenated EN + TE audio.
    """
    try:
        import edge_tts
    except Exception as exc:
        raise RuntimeError(f"edge-tts not available: {exc}") from exc

    async def _synthesize_one(text: str, lang: str) -> bytes:
        """Synthesize a single language segment."""
        if not text or not text.strip():
            return b""

        text = text.strip()
        if len(text) > 1800:
            text = text[:1800]

        voice = _DEFAULT_VOICE_FOR_LANG.get(lang, "en-IN-NeerjaNeural")

        # Check cache
        key = hashlib.sha256(f"{voice}\x00{text}".encode("utf-8")).hexdigest()
        cached = _voice_cache.get(key)
        if cached is not None:
            return cached

        # Synthesize
        audio = bytearray()
        async with _voice_lock:
            communicate = edge_tts.Communicate(text, voice)
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    audio.extend(chunk["data"])

        if not audio:
            return b""

        payload = bytes(audio)
        _voice_cache[key] = payload
        _voice_cache_order.append(key)
        while len(_voice_cache_order) > 24:
            _voice_cache.pop(_voice_cache_order.pop(0), None)

        return payload

    # Synthesize English (always)
    en_audio = await _synthesize_one(english_text, "en")

    # Synthesize Telugu if provided
    if telugu_text:
        te_audio = await _synthesize_one(telugu_text, "te")
        return en_audio + te_audio

    return en_audio


# Convenience function for testing
async def test_synthesize():
    """Test the synthesizer with sample agent results."""
    # Simulated agent results from a multi-agent run
    agent_results = [
        {
            "agent": "IntelX",
            "status": "completed",
            "result": "Threat intelligence scan completed. No active threats detected for the specified indicators. CVE-2024-12345 is patched in current firmware. Dark web monitoring shows no credential leaks for the monitored domains."
        },
        {
            "agent": "Memora",
            "status": "completed",
            "result": "Retrieved 3 relevant memories from the semantic store. Context includes: previous security audit from 2024-10-15, firewall rule changes from 2024-11-01, and VPN configuration baseline."
        },
        {
            "agent": "Cortex",
            "status": "completed",
            "result": "Lead scoring updated for 47 contacts. High-value segment increased by 12%. Attribution model shows organic search driving 34% of qualified pipeline. Campaign 'Q4 Security Push' has 2.3x ROI."
        },
        {
            "agent": "Stratex",
            "status": "completed",
            "result": "Portfolio rebalancing executed. Risk parity allocation applied. VaR reduced from 2.1% to 1.4%. Current positions: 40% equities, 30% bonds, 20% alternatives, 10% cash. Next rebalance scheduled for 2024-11-15."
        },
    ]

    user_goal = "Give me a security and portfolio status update for the quarterly review"

    print("=" * 60)
    print("USER GOAL:", user_goal)
    print("=" * 60)
    print("\nAGENT RESULTS:")
    for r in agent_results:
        print(f"  - {r['agent']}: {r['result'][:100]}...")
    print()

    # Test answer synthesis (will fail if Inference gateway not reachable)
    print("Testing answer synthesis via Inference gateway...")
    try:
        answer = await synthesize_answer(user_goal, agent_results)
        print("SYNTHESIZED ANSWER:")
        print("-" * 60)
        print(answer)
        print("-" * 60)
    except Exception as e:
        print(f"Inference gateway not available (expected in local dev): {e}")
        # Fallback: show what the prompt would look like
        results_text = "\n".join(
            f"  {i}. {r.get('agent', f'Agent {i}')} ({r.get('status', 'unknown')}): {r.get('result', r.get('output', r.get('content', str(r))))}"
            for i, r in enumerate(agent_results, 1)
        )
        answer = (
            f"[FALLBACK - Inference gateway unreachable]\n"
            f"User asked: {user_goal}\n\n"
            f"Agent results:\n{results_text}\n\n"
            f"[This would be synthesized into a natural answer by the LLM]"
        )
        print("FALLBACK ANSWER:")
        print("-" * 60)
        print(answer)
        print("-" * 60)

    # Test voice synthesis (uses local edge-tts)
    print("\nTesting voice synthesis (English)...")
    try:
        audio = await synthesize_voice(answer)
        print(f"Generated {len(audio)} bytes of audio")
    except Exception as e:
        print(f"Voice synthesis failed: {e}")

    # Test bilingual
    telugu_version = "ఈ రిపోర్ట్ సురక్షితంగా మరియు పోర్ట్ఫోలియో సంతులితంగా ఉంది."
    print("\nTesting bilingual voice synthesis (English + Telugu)...")
    try:
        audio_bilingual = await synthesize_voice(answer, telugu_version)
        print(f"Generated {len(audio_bilingual)} bytes of bilingual audio")
    except Exception as e:
        print(f"Bilingual voice synthesis failed: {e}")

    return answer


if __name__ == "__main__":
    asyncio.run(test_synthesize())