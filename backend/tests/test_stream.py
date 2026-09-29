"""Streaming endpoints send each trace step as it happens, then the same turn response as the JSON API."""

import json

from app import db
from tests.conftest import call, say

REFUND_1001 = {"order_id": "ORD-1001", "email": "maria.lopez@example.com", "reason": "Broken"}


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def start(client) -> str:
    return client.post("/conversations").json()["conversation_id"]


def test_message_stream_sends_steps_then_the_turn(make_client):
    with make_client(call("get_order_status", order_id="ORD-1001", email="maria.lopez@example.com"),
                     say("It was delivered on 10 September.")) as client:
        response = client.post(f"/conversations/{start(client)}/messages/stream", json={"message": "Where is ORD-1001?"})

    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert [name for name, _ in events] == ["step", "step", "step", "turn"]
    assert [data["type"] for _, data in events[:3]] == ["llm", "tool", "llm"]
    turn = events[-1][1]
    assert turn["reply"] == "It was delivered on 10 September."
    assert turn["trace"]["steps"] == [data for _, data in events[:3]]


def test_approval_flow_over_the_stream(make_client, tmp_path):
    with make_client(call("create_refund", **REFUND_1001), say("Refund approved.")) as client:
        conversation = start(client)
        paused = parse_sse(client.post(f"/conversations/{conversation}/messages/stream", json={"message": "Refund"}).text)
        assert paused[-1][1]["status"] == "awaiting_approval"
        assert paused[-1][1]["approval"]["amount"] == 79.0

        done = parse_sse(client.post(f"/conversations/{conversation}/approval/stream", json={"decision": "approve"}).text)
        assert [data["type"] for name, data in done if name == "step"] == ["approval", "tool", "llm"]
        assert done[-1][1]["reply"] == "Refund approved."

    with db.connect(tmp_path / "store.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM refunds WHERE order_id = 'ORD-1001'").fetchone()[0] == 1


def test_claim_guard_step_is_streamed(make_client):
    with make_client(say("I've escalated this. Your ticket ID is TCK-0001.")) as client:
        events = parse_sse(client.post(f"/conversations/{start(client)}/messages/stream", json={"message": "Help"}).text)
    assert events[-2][1]["type"] == "claim_guard"
    assert "TCK-0001" not in events[-1][1]["reply"]


def test_stream_errors_before_start_are_http_errors(make_client):
    with make_client() as client:
        conversation = start(client)
        assert client.post("/conversations/nope/messages/stream", json={"message": "Hi"}).status_code == 404
        assert client.post(f"/conversations/{conversation}/approval/stream", json={"decision": "approve"}).status_code == 409


def test_failure_after_start_becomes_an_error_event(make_client):
    with make_client() as client:  # no scripted replies, so the model fails mid-turn
        events = parse_sse(client.post(f"/conversations/{start(client)}/messages/stream", json={"message": "Hi"}).text)
    assert events == [("error", {"detail": "Something went wrong on our side. Please try again."})]
