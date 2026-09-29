"""HTTP layer: routes, status codes and response shapes."""

from tests.conftest import call, say

REFUND_1001 = {"order_id": "ORD-1001", "email": "maria.lopez@example.com", "reason": "Broken"}


def start(client) -> str:
    return client.post("/conversations").json()["conversation_id"]


def test_health(make_client):
    with make_client() as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_message_returns_reply_and_trace(make_client):
    with make_client(say("Hello! How can I help?")) as client:
        response = client.post(f"/conversations/{start(client)}/messages", json={"message": "Hi"})
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Hello! How can I help?"
    assert body["status"] == "done"
    assert body["trace"]["turn"] == 1


def test_approval_flow_over_http(make_client):
    with make_client(call("create_refund", **REFUND_1001), say("Refund approved.")) as client:
        conversation = start(client)
        paused = client.post(f"/conversations/{conversation}/messages", json={"message": "Refund please"})
        assert paused.json()["status"] == "awaiting_approval"

        blocked = client.post(f"/conversations/{conversation}/messages", json={"message": "Hello?"})
        assert blocked.status_code == 409

        done = client.post(f"/conversations/{conversation}/approval", json={"decision": "approve"})
        assert done.json()["reply"] == "Refund approved."

        stored = client.get(f"/conversations/{conversation}").json()
        assert [m["role"] for m in stored["messages"]] == ["user", "assistant"]
        assert stored["pending_approval"] is None


def test_errors(make_client):
    with make_client() as client:
        conversation = start(client)
        assert client.post("/conversations/nope/messages", json={"message": "Hi"}).status_code == 404
        assert client.get("/conversations/nope").status_code == 404
        assert client.post(f"/conversations/{conversation}/messages", json={"message": ""}).status_code == 422
        assert client.post(f"/conversations/{conversation}/approval", json={"decision": "maybe"}).status_code == 422
        assert client.post(f"/conversations/{conversation}/approval", json={"decision": "approve"}).status_code == 409
