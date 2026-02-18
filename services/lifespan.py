"""
lifespan.py  –  FastAPI lifespan integration
─────────────────────────────────────────────
Add this lifespan to your FastAPI app to initialise the LangGraph
chatbot graph (with SQLite checkpointer) at startup.

Usage in your main.py / app factory:
─────────────────────────────────────
    from lifespan import lifespan
    app = FastAPI(lifespan=lifespan)
    app.include_router(chat_router)

Requirements (add to requirements.txt):
    langgraph>=0.2.0
    langchain-openai>=0.1.0
    langchain-core>=0.2.0
    aiosqlite>=0.19.0
    openai>=1.0.0
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from loguru import logger

from services.chat_graph import build_graph


# Path to the SQLite database file that stores conversation checkpoints.
# Override via LANGGRAPH_SQLITE_PATH environment variable.
SQLITE_PATH = os.getenv("LANGGRAPH_SQLITE_PATH", "chat_memory.db")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan handler.

    On startup  → create AsyncSqliteSaver, compile LangGraph graph, store on app.state
    On shutdown → close the SQLite connection cleanly
    """
    logger.info("🤖 Initialising LangGraph chatbot graph …")

    async with AsyncSqliteSaver.from_conn_string(SQLITE_PATH) as checkpointer:
        # Build and compile the graph once
        graph = build_graph(checkpointer)
        app.state.chat_graph = graph
        logger.info(f"✅ Chatbot graph ready  (SQLite: {SQLITE_PATH})")

        yield   # ← application runs here

    # Cleanup (checkpointer context manager closes the connection)
    logger.info("🛑 Chatbot graph shut down.")
    app.state.chat_graph = None