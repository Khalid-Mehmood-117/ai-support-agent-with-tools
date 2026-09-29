"""FastAPI app. Run from the backend folder: uvicorn app.main:app --reload"""

import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver

from app.config import Settings
from app.graph import build_graph
from app.routers import conversations
from app.seed import ensure_database
from app.service import SupportService
from app.tools import ToolContext


def create_app(settings: Settings | None = None, model: BaseChatModel | None = None) -> FastAPI:
    """Build the app. Tests pass their own settings and a fake model."""
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db_path = settings.resolve(settings.database_path)
        checkpoint_path = settings.resolve(settings.checkpoint_path)
        ensure_database(db_path)

        checkpoint_conn = sqlite3.connect(checkpoint_path, check_same_thread=False)
        chat_model = model or ChatOpenAI(
            model=settings.openai_model, temperature=0, api_key=settings.openai_api_key
        )
        graph = build_graph(
            chat_model,
            ToolContext(db_path=db_path, today=settings.store_today),
            settings.max_tool_steps,
            checkpointer=SqliteSaver(checkpoint_conn),
        )
        app.state.service = SupportService(graph, db_path)
        yield
        checkpoint_conn.close()

    app = FastAPI(title="AI Support Agent with Tools", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(conversations.router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
