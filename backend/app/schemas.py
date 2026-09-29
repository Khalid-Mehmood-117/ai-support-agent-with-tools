"""Request and response models for the API."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ConversationCreated(BaseModel):
    conversation_id: str


class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ApprovalIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=500)


class Trace(BaseModel):
    turn: int
    duration_ms: int
    steps: list[dict[str, Any]]


class TurnOut(BaseModel):
    reply: str | None
    status: Literal["done", "awaiting_approval"]
    approval: dict[str, Any] | None
    trace: Trace


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ConversationOut(BaseModel):
    conversation_id: str
    messages: list[ChatMessage]
    traces: list[Trace]
    pending_approval: dict[str, Any] | None
