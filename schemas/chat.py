from typing import Annotated, Any, Optional
from pydantic import BaseModel
import operator


# ──────────────────────────────────────────────────────────────────
# LangGraph State  (reducer: messages list is appended, not replaced)
# ──────────────────────────────────────────────────────────────────
class ChatState(dict):
    """
    Typed dict used as LangGraph state.
    Keys:
        messages        – full conversation history (HumanMessage / AIMessage)
        user_id         – UUID string of authenticated patient
        thread_id       – session identifier (used for SQLite checkpointer)
        in_scope        – bool: did the guard node approve the last user turn?
        tool_result     – raw dict result from the last tool call (cleared each turn)
        pending_booking – dict holding collected booking params waiting for confirmation
        streaming_tokens– accumulated streaming output (for SSE)
    """
    pass


# ──────────────────────────────────────────────────────────────────
# HTTP Request / Response models
# ──────────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    thread_id: str                  # frontend generates UUID per session


class ChatResponse(BaseModel):
    reply: str
    thread_id: str