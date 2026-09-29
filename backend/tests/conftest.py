"""Shared test helpers: a scripted fake chat model and a fresh seeded database per test."""

import itertools

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from app.config import Settings
from app.graph import build_graph
from app.main import create_app
from app.seed import create_database
from app.service import SupportService
from app.tools import ToolContext

TODAY = Settings.model_fields["store_today"].default
_call_ids = itertools.count(1)


class ScriptedModel(BaseChatModel):
    """Returns the queued replies in order and records the messages it was given."""

    replies: list[AIMessage] = Field(default_factory=list)
    prompts: list[list] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.prompts.append(messages)
        if not self.replies:
            raise AssertionError("The scripted model ran out of replies")
        return ChatResult(generations=[ChatGeneration(message=self.replies.pop(0))])


def say(text: str) -> AIMessage:
    return AIMessage(content=text)


def call(name: str, **args) -> AIMessage:
    """One tool call. Use calls() for several in the same model reply."""
    return calls((name, args))


def calls(*items: tuple[str, dict]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": f"call_{next(_call_ids)}"} for name, args in items],
    )


@pytest.fixture
def ctx(tmp_path) -> ToolContext:
    db_path = tmp_path / "store.db"
    create_database(db_path)
    return ToolContext(db_path=db_path, today=TODAY)


@pytest.fixture
def make_service(ctx):
    def factory(*replies: AIMessage, max_tool_steps: int = 6) -> tuple[SupportService, ScriptedModel]:
        model = ScriptedModel(replies=list(replies))
        graph = build_graph(model, ctx, max_tool_steps, checkpointer=InMemorySaver())
        return SupportService(graph, ctx.db_path), model

    return factory


@pytest.fixture
def make_client(tmp_path):
    def factory(*replies: AIMessage) -> TestClient:
        settings = Settings(
            _env_file=None,
            openai_api_key="test-key",
            database_path=tmp_path / "store.db",
            checkpoint_path=tmp_path / "checkpoints.db",
        )
        return TestClient(create_app(settings, ScriptedModel(replies=list(replies))))

    return factory
