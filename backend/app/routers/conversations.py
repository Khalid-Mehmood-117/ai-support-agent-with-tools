"""Conversation endpoints: start a chat, send messages, approve or reject refunds."""

from collections.abc import Iterator
from contextlib import contextmanager

import openai
from fastapi import APIRouter, HTTPException, Request

from app.schemas import ApprovalIn, ConversationCreated, ConversationOut, MessageIn, TurnOut
from app.service import ConversationConflict, ConversationNotFound, SupportService

router = APIRouter(prefix="/conversations", tags=["conversations"])


def get_service(request: Request) -> SupportService:
    return request.app.state.service


@contextmanager
def http_errors() -> Iterator[None]:
    """Translate service errors into HTTP responses."""
    try:
        yield
    except ConversationNotFound:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    except ConversationConflict as error:
        raise HTTPException(status_code=409, detail=str(error))
    except openai.OpenAIError:
        raise HTTPException(status_code=502, detail="The language model is not available. Please try again.")


# Plain def (not async): FastAPI runs these in a thread pool, and the agent code is synchronous.

@router.post("", response_model=ConversationCreated)
def create_conversation(request: Request) -> dict:
    return {"conversation_id": get_service(request).create_conversation()}


@router.post("/{conversation_id}/messages", response_model=TurnOut)
def send_message(conversation_id: str, body: MessageIn, request: Request) -> dict:
    with http_errors():
        return get_service(request).send_message(conversation_id, body.message)


@router.post("/{conversation_id}/approval", response_model=TurnOut)
def resolve_approval(conversation_id: str, body: ApprovalIn, request: Request) -> dict:
    with http_errors():
        return get_service(request).resolve_approval(conversation_id, body.decision, body.note)


@router.get("/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: str, request: Request) -> dict:
    with http_errors():
        return get_service(request).get_conversation(conversation_id)
