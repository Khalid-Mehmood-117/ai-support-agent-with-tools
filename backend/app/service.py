"""Conversation logic between the API routes and the LangGraph agent."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from app import db


class ConversationNotFound(Exception):
    pass


class ConversationConflict(Exception):
    """The request does not fit the conversation state, for example a message during an approval."""


class SupportService:
    def __init__(self, graph, db_path: Path):
        self.graph = graph
        self.db_path = db_path

    def create_conversation(self) -> str:
        conversation_id = str(uuid.uuid4())
        with db.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO conversations (id, created_at) VALUES (?, ?)",
                (conversation_id, datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
        return conversation_id

    def send_message(self, conversation_id: str, message: str) -> dict:
        snapshot = self._snapshot(conversation_id)
        if snapshot.interrupts:
            raise ConversationConflict("A refund is waiting for staff approval. Approve or reject it first.")
        turn = snapshot.values.get("turn", 0) + 1
        self.graph.invoke({"messages": [HumanMessage(message)], "turn": turn}, self._config(conversation_id))
        return self._turn_result(conversation_id)

    def resolve_approval(self, conversation_id: str, decision: str, note: str) -> dict:
        if not self._snapshot(conversation_id).interrupts:
            raise ConversationConflict("There is no refund waiting for approval in this conversation.")
        self.graph.invoke(Command(resume={"decision": decision, "note": note}), self._config(conversation_id))
        return self._turn_result(conversation_id)

    def get_conversation(self, conversation_id: str) -> dict:
        snapshot = self._snapshot(conversation_id)
        messages = [
            {"role": "user" if isinstance(m, HumanMessage) else "assistant", "content": m.content}
            for m in snapshot.values.get("messages", [])
            if isinstance(m, (HumanMessage, AIMessage)) and m.content
        ]
        with db.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT trace FROM traces WHERE conversation_id = ? ORDER BY turn", (conversation_id,)
            ).fetchall()
        return {
            "conversation_id": conversation_id,
            "messages": messages,
            "traces": [json.loads(row["trace"]) for row in rows],
            "pending_approval": snapshot.interrupts[0].value if snapshot.interrupts else None,
        }

    def _turn_result(self, conversation_id: str) -> dict:
        """Build the response for the current turn and store its trace."""
        snapshot = self._snapshot(conversation_id)
        turn = snapshot.values["turn"]
        trace = build_trace(snapshot.values["steps"], turn)
        self._save_trace(conversation_id, trace)

        if snapshot.interrupts:
            return {"reply": None, "status": "awaiting_approval", "approval": snapshot.interrupts[0].value, "trace": trace}
        return {"reply": snapshot.values["messages"][-1].content, "status": "done", "approval": None, "trace": trace}

    def _save_trace(self, conversation_id: str, trace: dict) -> None:
        with db.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO traces (conversation_id, turn, trace) VALUES (?, ?, ?)",
                (conversation_id, trace["turn"], json.dumps(trace)),
            )

    def _snapshot(self, conversation_id: str):
        with db.connect(self.db_path) as conn:
            exists = conn.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        if not exists:
            raise ConversationNotFound(conversation_id)
        return self.graph.get_state(self._config(conversation_id))

    @staticmethod
    def _config(conversation_id: str) -> dict:
        return {"configurable": {"thread_id": conversation_id}, "recursion_limit": 50}


def build_trace(all_steps: list[dict], turn: int) -> dict:
    """The trace of one turn. duration_ms is working time, so it excludes time waiting for staff."""
    steps = [{k: v for k, v in step.items() if k != "turn"} for step in all_steps if step["turn"] == turn]
    return {"turn": turn, "duration_ms": sum(step.get("duration_ms", 0) for step in steps), "steps": steps}
