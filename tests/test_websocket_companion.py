"""Integration tests for the real-time WebSocket companion event multiplexer."""

import pytest
from starlette.testclient import TestClient

from friday.api.companion_ws import companion_multiplexer
from friday.api.server import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("FRIDAY_API_KEY", raising=False)
    monkeypatch.delenv("FRIDAY_UNIVERSE_API_KEY", raising=False)
    with TestClient(app) as test_client:
        yield test_client


def receive_until_type(ws, target_type: str, max_packets: int = 10) -> dict:
    """Helper to consume multiplexed packets until the desired event type arrives."""
    for _ in range(max_packets):
        packet = ws.receive_json()
        if packet.get("type") == target_type:
            return packet
    raise AssertionError(f"Expected event type '{target_type}' not received within {max_packets} packets")


def test_companion_ws_connection_and_welcome(client: TestClient):
    with client.websocket_connect("/ws/companion") as ws:
        msg = receive_until_type(ws, "welcome")
        assert msg["type"] == "welcome"
        assert "client_id" in msg
        assert "telemetry" in msg["topics"]
        assert "system" in msg["topics"]


def test_companion_ws_custom_topics_query_param(client: TestClient):
    with client.websocket_connect("/ws/companion?topics=reflex,tasks") as ws:
        msg = receive_until_type(ws, "welcome")
        assert msg["type"] == "welcome"
        assert sorted(msg["topics"]) == ["reflex", "tasks"]


def test_companion_ws_telemetry_streaming(client: TestClient):
    """Verify that clients subscribed to telemetry receive live system telemetry broadcasts."""
    with client.websocket_connect("/ws/companion?topics=telemetry") as ws:
        receive_until_type(ws, "welcome")
        telemetry_pkt = receive_until_type(ws, "system_telemetry")
        assert telemetry_pkt["type"] == "system_telemetry"
        assert telemetry_pkt["topic"] == "telemetry"
        assert "data" in telemetry_pkt
        assert "cpu_percent" in telemetry_pkt["data"] or "timestamp" in telemetry_pkt


def test_companion_ws_ping_pong_heartbeat(client: TestClient):
    with client.websocket_connect("/ws/companion?topics=system") as ws:
        receive_until_type(ws, "welcome")

        ws.send_json({"type": "ping", "timestamp": "2026-10-21T12:00:00Z"})
        reply = receive_until_type(ws, "pong")
        assert reply["type"] == "pong"
        assert reply["client_timestamp"] == "2026-10-21T12:00:00Z"
        assert "timestamp" in reply


def test_companion_ws_topic_subscription_lifecycle(client: TestClient):
    with client.websocket_connect("/ws/companion?topics=system") as ws:
        receive_until_type(ws, "welcome")

        # Subscribe to reflex
        ws.send_json({"type": "subscribe", "topics": ["reflex", "tasks"]})
        sub_reply = receive_until_type(ws, "subscription_updated")
        assert sub_reply["type"] == "subscription_updated"
        assert "reflex" in sub_reply["topics"]
        assert "tasks" in sub_reply["topics"]

        # Unsubscribe from reflex
        ws.send_json({"type": "unsubscribe", "topics": ["reflex"]})
        unsub_reply = receive_until_type(ws, "subscription_updated")
        assert unsub_reply["type"] == "subscription_updated"
        assert "reflex" not in unsub_reply["topics"]
        assert "tasks" in unsub_reply["topics"]


def test_companion_ws_snapshot_query(client: TestClient):
    with client.websocket_connect("/ws/companion?topics=system") as ws:
        receive_until_type(ws, "welcome")

        ws.send_json({"type": "get_snapshot"})
        reply = receive_until_type(ws, "snapshot")
        assert reply["type"] == "snapshot"
        assert reply["status"] == "ok"
        assert isinstance(reply["data"], dict)


def test_companion_ws_command_execution(client: TestClient):
    with client.websocket_connect("/ws/companion?topics=system") as ws:
        receive_until_type(ws, "welcome")

        ws.send_json({"type": "command", "command": "time"})
        reply = receive_until_type(ws, "command_reply")
        assert reply["type"] == "command_reply"
        assert reply["command"] == "time"
        assert "reply" in reply


@pytest.mark.asyncio
async def test_companion_multiplexer_broadcast_filtering():
    """Verify that events only deliver to clients subscribed to the relevant topic."""
    from unittest.mock import AsyncMock

    mock_ws1 = AsyncMock()
    mock_ws2 = AsyncMock()

    sub1 = await companion_multiplexer.connect(mock_ws1, client_id="sub1", initial_topics={"reflex"})
    sub2 = await companion_multiplexer.connect(mock_ws2, client_id="sub2", initial_topics={"tasks"})

    try:
        # Broadcast reflex event
        delivered = await companion_multiplexer.broadcast("reflex", "incident", {"id": "inc_001"})
        assert delivered == 1
        mock_ws1.send_json.assert_called_once()
        sent_envelope = mock_ws1.send_json.call_args[0][0]
        assert sent_envelope["topic"] == "reflex"
        assert sent_envelope["data"]["id"] == "inc_001"
        mock_ws2.send_json.assert_not_called()

        # Broadcast tasks event
        mock_ws1.reset_mock()
        mock_ws2.reset_mock()
        delivered = await companion_multiplexer.broadcast("tasks", "task_sweep", {"active_tasks": 3})
        assert delivered == 1
        mock_ws2.send_json.assert_called_once()
        mock_ws1.send_json.assert_not_called()
    finally:
        await companion_multiplexer.disconnect(mock_ws1)
        await companion_multiplexer.disconnect(mock_ws2)


def test_companion_status_http_endpoint(client: TestClient):
    resp = client.get("/api/companion/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "active_clients" in data
    assert "telemetry_streaming" in data
    assert isinstance(data["clients"], list)
