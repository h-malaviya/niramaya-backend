
from __future__ import annotations

import json
from datetime import date
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, BaseMessage, ToolMessage
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from database.postgres import get_db
from dependencies.auth import get_current_user
from schemas.chat import ChatRequest
from schemas.schemas import User
from services.chat_tools import set_tool_context

router = APIRouter(prefix="/chat", tags=["Chatbot"])


# ─────────────────────────────────────────────────────────────────────────────
# Helper – pretty-format message history for GET /history
# ─────────────────────────────────────────────────────────────────────────────

def _serialise_message(msg: BaseMessage) -> dict:
    return {
        "role": msg.type,   # "human" | "ai" | "tool"
        "content": msg.content,
    }


# ─────────────────────────────────────────────────────────────────────────────
# SSE token generator
# ─────────────────────────────────────────────────────────────────────────────

# async def _stream_graph(
#         graph,
#         input_state: dict,
#         config: dict,
#     ) -> AsyncGenerator[str, None]:
#     """
#     Runs the LangGraph graph and yields SSE events.

#     Event types:
#       data: {"type": "token",  "content": "..."}   – streaming AI token
#       data: {"type": "tool_start", "tool": "..."}  – tool about to run
#       data: {"type": "tool_end",   "tool": "...", "result": {...}}  – tool done
#       data: {"type": "done",   "content": "..."}   – final full reply
#       data: {"type": "error",  "content": "..."}   – error
#     """
#     final_content = ""

#     def _extract_token(chunk) -> str:
#         """
#         Safely pull text from an LLM stream chunk.
#         Handles both plain strings and the list-of-dicts format that
#         OpenRouter / newer LangChain versions can return.
#         """
#         content = getattr(chunk, "content", "")
#         if isinstance(content, str):
#             return content
#         # content is a list like [{"type": "text", "text": "hello"}]
#         if isinstance(content, list):
#             parts = []
#             for block in content:
#                 if isinstance(block, dict):
#                     parts.append(block.get("text", ""))
#                 elif isinstance(block, str):
#                     parts.append(block)
#             return "".join(parts)
#         return ""

#     try:
#         async for event in graph.astream_events(input_state, config=config, version="v2"):
#             kind = event.get("event")
#             data = event.get("data", {})
#             tags = event.get("tags", [])

#             # ── Only capture tokens from the agent LLM, not the guard LLM ─────
#             # The guard LLM is tagged "guard" in chat_graph.py
#             if kind == "on_chat_model_stream" and "guard" not in tags:
#                 try:
#                     chunk = data.get("chunk")
#                     if chunk:
#                         token = _extract_token(chunk)
#                         if token:
#                             final_content += token
#                             try:
#                                 yield f"data: {json.dumps({"type": "token", "content": token})}\n\n"
#                             except Exception as e:
#                                 logger.warning("Error serializing token: {}", e)
#                 except Exception as e:
#                     logger.warning("Error processing chat model stream: {}", e)
#                     continue

#             # ── Tool started ──────────────────────────────────────────────────
#             elif kind == "on_tool_start":
#                 try:
#                     tool_name = event.get("name", "")
#                     yield f"data: {json.dumps({"type": "tool_start", "tool": tool_name})}\n\n"
#                 except Exception as e:
#                     logger.warning("Error serializing tool_start: {}", e)
#                     continue

#             # ── Tool finished ─────────────────────────────────────────────────
#             elif kind == "on_tool_end":
#                 tool_name = event.get("name", "")
#                 try:
#                     # Safely get output - it might be in different places or formats
#                     output = data.get("output") or data.get("chunk") or ""
                    
#                     # Log for debugging (only in debug mode to avoid spam)
#                     preview = str(output)[:100] if output else "None"
#                     logger.debug("Tool {} output type: {}, value preview: {}", tool_name, type(output), preview)
                    
#                     # Handle ToolMessage objects
#                     if isinstance(output, ToolMessage):
#                         output = output.content
#                     elif hasattr(output, 'content'):
#                         # Handle any object with a content attribute
#                         output = getattr(output, 'content', output)
                    
#                     # Handle None or empty output
#                     if output is None:
#                         result = {}
#                     # Handle different output formats from LangGraph
#                     elif isinstance(output, str):
#                         # Check if it's empty or whitespace
#                         if not output.strip():
#                             result = {}
#                         else:
#                             # Try to parse as JSON first
#                             try:
#                                 result = json.loads(output)
#                                 # Check if result is itself a JSON string (double-encoded)
#                                 if isinstance(result, str):
#                                     try:
#                                         result = json.loads(result)
#                                     except (json.JSONDecodeError, TypeError):
#                                         # It's just a string, keep it as-is
#                                         pass
#                             except (json.JSONDecodeError, TypeError) as json_err:
#                                 # If not valid JSON, use as-is
#                                 logger.debug("Output is not JSON for {}, using as string: {}", tool_name, json_err)
#                                 result = output
#                     elif isinstance(output, (dict, list)):
#                         # Already parsed, use directly
#                         result = output
#                     elif isinstance(output, bytes):
#                         # Handle bytes - decode to string first
#                         try:
#                             output_str = output.decode('utf-8')
#                             result = json.loads(output_str) if output_str.strip() else {}
#                         except (UnicodeDecodeError, json.JSONDecodeError):
#                             result = str(output)
#                     else:
#                         # Convert other types to string
#                         result = str(output)
                    
#                     # Safely serialize the result
#                     try:
#                         result_json = json.dumps({"type": "tool_end", "tool": tool_name, "result": result}, default=str)
#                         yield f"data: {result_json}\n\n"
#                     except (TypeError, ValueError) as serialize_error:
#                         logger.opt(exception=True).error(
#                             "Error serializing tool result for {}: {}", tool_name, serialize_error
#                         )
#                         # Fallback: send error message with string representation
#                         try:
#                             error_msg = json.dumps({
#                                 "type": "tool_end", 
#                                 "tool": tool_name, 
#                                 "result": {"error": "Failed to serialize tool result", "raw": str(result)[:200]}
#                             })
#                             yield f"data: {error_msg}\n\n"
#                         except Exception:
#                             # Last resort: send minimal error
#                             yield f'data: {{"type": "tool_end", "tool": "{tool_name}", "result": {{"error": "Serialization failed"}}}}\n\n'
                            
#                 except Exception as tool_error:
#                     logger.opt(exception=True).error("Error in on_tool_end for {}: {}", tool_name, tool_error)
#                     # Continue processing other events instead of breaking the stream
#                     try:
#                         error_msg = json.dumps({
#                             "type": "tool_end",
#                             "tool": tool_name,
#                             "result": {"error": f"Tool execution error: {str(tool_error)[:100]}"}
#                         })
#                         yield f"data: {error_msg}\n\n"
#                     except Exception:
#                         pass
#                     continue

#     except Exception as e:
#         logger.opt(exception=True).error("Graph streaming error: {}", e)
#         try:
#             yield f"data: {json.dumps({"type": "error", "content": "Something went wrong. Please try again."})}\n\n"
#         except Exception:
#             pass
#         return

#     # ── Check final state for non-streamed messages (e.g., from guard node) ─────
#     # This handles cases where guard node returns AIMessage and routes to __end__
#     try:
#         final_state = await graph.aget_state(config)
#         messages = final_state.values.get("messages", [])
#         # Find the last AIMessage that wasn't streamed (guard node responses)
#         for msg in reversed(messages):
#             if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
#                 msg_content = msg.content
#                 if isinstance(msg_content, str) and msg_content and msg_content not in final_content:
#                     # This is a guard node response that wasn't streamed
#                     final_content = msg_content
#                     # Stream it as tokens for consistency
#                     try:
#                         for char in msg_content:
#                             yield f"data: {json.dumps({"type": "token", "content": char})}\n\n"
#                     except Exception as e:
#                         logger.warning("Error streaming guard message: {}", e)
#                         # Fallback: send entire message at once
#                         try:
#                             yield f"data: {json.dumps({"type": "token", "content": msg_content})}\n\n"
#                         except Exception:
#                             pass
#                     break
#     except Exception as e:
#         logger.debug("Could not check final state for guard messages: {}", e)

#     # Final done event – always send the accumulated content
#     yield f"data: {json.dumps({"type": "done", "content": final_content})}\n\n"

async def _stream_graph(
        graph,
        input_state: dict,
        config: dict,
    ) -> AsyncGenerator[str, None]:
    """
    Runs the LangGraph graph and yields SSE events.

    Event types:
      data: {"type": "token",  "content": "..."}   – streaming AI token
      data: {"type": "tool_start", "tool": "..."}  – tool about to run
      data: {"type": "tool_end",   "tool": "...", "result": {...}}  – tool done
      data: {"type": "done",   "content": "..."}   – final full reply
      data: {"type": "error",  "content": "..."}   – error
    """
    final_content = ""

    def _extract_token(chunk) -> str:
        """
        Safely pull text from an LLM stream chunk.
        Handles both plain strings and the list-of-dicts format that
        OpenRouter / newer LangChain versions can return.
        """
        content = getattr(chunk, "content", "")
        if isinstance(content, str):
            return content
        # content is a list like [{"type": "text", "text": "hello"}]
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
            return "".join(parts)
        return ""

    try:
        async for event in graph.astream_events(input_state, config=config, version="v2"):
            kind = event.get("event")
            data = event.get("data", {})
            tags = event.get("tags", [])

            # ── Only capture tokens from the agent LLM, not the guard LLM ─────
            # The guard LLM is tagged "guard" in chat_graph.py
            if kind == "on_chat_model_stream" and "guard" not in tags:
                try:
                    chunk = data.get("chunk")
                    if chunk:
                        token = _extract_token(chunk)
                        if token:
                            final_content += token
                            try:
                                yield f"data: {json.dumps({"type": "token", "content": token})}\n\n"
                            except Exception as e:
                                logger.warning("Error serializing token: {}", e)
                except Exception as e:
                    logger.warning("Error processing chat model stream: {}", e)
                    continue

            # ── Tool started ──────────────────────────────────────────────────
            elif kind == "on_tool_start":
                try:
                    tool_name = event.get("name", "")
                    yield f"data: {json.dumps({"type": "tool_start", "tool": tool_name})}\n\n"
                except Exception as e:
                    logger.warning("Error serializing tool_start: {}", e)
                    continue

            # ── Tool finished ─────────────────────────────────────────────────
            elif kind == "on_tool_end":
                tool_name = event.get("name", "")
                try:
                    # Safely get output - it might be in different places or formats
                    output = data.get("output") or data.get("chunk") or ""
                    
                    # Log for debugging (only in debug mode to avoid spam)
                    preview = str(output)[:100] if output else "None"
                    logger.debug("Tool {} output type: {}, value preview: {}", tool_name, type(output), preview)
                    
                    # Handle ToolMessage objects
                    if isinstance(output, ToolMessage):
                        output = output.content
                    elif hasattr(output, 'content'):
                        # Handle any object with a content attribute
                        output = getattr(output, 'content', output)
                    
                    # Handle None or empty output
                    if output is None:
                        result = {}
                    # Handle different output formats from LangGraph
                    elif isinstance(output, str):
                        # Check if it's empty or whitespace
                        if not output.strip():
                            result = {}
                        else:
                            # Try to parse as JSON first
                            try:
                                result = json.loads(output)
                                # Check if result is itself a JSON string (double-encoded)
                                if isinstance(result, str):
                                    try:
                                        result = json.loads(result)
                                    except (json.JSONDecodeError, TypeError):
                                        # It's just a string, keep it as-is
                                        pass
                            except (json.JSONDecodeError, TypeError) as json_err:
                                # If not valid JSON, use as-is
                                logger.debug("Output is not JSON for {}, using as string: {}", tool_name, json_err)
                                result = output
                    elif isinstance(output, (dict, list)):
                        # Already parsed, use directly
                        result = output
                    elif isinstance(output, bytes):
                        # Handle bytes - decode to string first
                        try:
                            output_str = output.decode('utf-8')
                            result = json.loads(output_str) if output_str.strip() else {}
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            result = str(output)
                    else:
                        # Convert other types to string
                        result = str(output)
                    
                    # Safely serialize the result
                    try:
                        result_json = json.dumps({"type": "tool_end", "tool": tool_name, "result": result}, default=str)
                        yield f"data: {result_json}\n\n"
                    except (TypeError, ValueError) as serialize_error:
                        logger.opt(exception=True).error(
                            "Error serializing tool result for {}: {}", tool_name, serialize_error
                        )
                        # Fallback: send error message with string representation
                        try:
                            error_msg = json.dumps({
                                "type": "tool_end", 
                                "tool": tool_name, 
                                "result": {"error": "Failed to serialize tool result", "raw": str(result)[:200]}
                            })
                            yield f"data: {error_msg}\n\n"
                        except Exception:
                            # Last resort: send minimal error
                            yield f'data: {{"type": "tool_end", "tool": "{tool_name}", "result": {{"error": "Serialization failed"}}}}\n\n'
                            
                except Exception as tool_error:
                    logger.opt(exception=True).error("Error in on_tool_end for {}: {}", tool_name, tool_error)
                    # Continue processing other events instead of breaking the stream
                    try:
                        error_msg = json.dumps({
                            "type": "tool_end",
                            "tool": tool_name,
                            "result": {"error": f"Tool execution error: {str(tool_error)[:100]}"}
                        })
                        yield f"data: {error_msg}\n\n"
                    except Exception:
                        pass
                    continue

    except Exception as e:
        logger.opt(exception=True).error("Graph streaming error: {}", e)
        try:
            yield f"data: {json.dumps({"type": "error", "content": "Something went wrong. Please try again."})}\n\n"
        except Exception:
            pass
        return

    # ── Check final state for non-streamed messages (e.g., from guard node) ─────
    # ONLY run when NO tokens were streamed. If final_content is non-empty the
    # agent already streamed its reply via on_chat_model_stream – walking the
    # full message history here would append OLD messages to the current reply.
    if not final_content:
        try:
            final_state = await graph.aget_state(config)
            state_messages = final_state.values.get("messages", [])
            # Find the last AIMessage – must be the guard node response
            for msg in reversed(state_messages):
                if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
                    msg_content = msg.content
                    if isinstance(msg_content, str) and msg_content:
                        final_content = msg_content
                        try:
                            yield f"data: {json.dumps({'type': 'token', 'content': msg_content})}\n\n"
                        except Exception as e:
                            logger.warning("Error streaming guard message: {}", e)
                    break
        except Exception as e:
            logger.debug("Could not check final state for guard messages: {}", e)

    # Final done event – always send the accumulated content
    yield f"data: {json.dumps({"type": "done", "content": final_content})}\n\n"


# ─────────────────────────────────────────────────────────────────────────────
# POST /chat/message
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/message")
async def chat_message(
    payload: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Main chat endpoint.  Returns a streaming SSE response.

    The client must:
      1. Send `Accept: text/event-stream` or parse the chunked response
      2. Include `Authorization: Bearer <token>` header
      3. Provide a stable `thread_id` (UUID) per conversation session

    SSE event format:
      data: {"type": "token",      "content": "<partial text>"}
      data: {"type": "tool_start", "tool": "<tool_name>"}
      data: {"type": "tool_end",   "tool": "<tool_name>", "result": {...}}
      data: {"type": "done",       "content": "<full reply>"}
      data: {"type": "error",      "content": "<error message>"}
    """
    # Inject DB + user into tool context (context var – safe per async task)
    set_tool_context(db=db, user=current_user)

    graph = request.app.state.chat_graph
    if graph is None:
        raise HTTPException(500, "Chatbot graph not initialised")

    config = {
        "configurable": {"thread_id": payload.thread_id},
        "recursion_limit": 25,
    }

    input_state = {
        "messages": [HumanMessage(content=payload.message)],
        "user_id": str(current_user.id),
        "thread_id": payload.thread_id,
        "in_scope": True,
    }

    return StreamingResponse(
        _stream_graph(graph, input_state, config),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",       # disable nginx buffering
            "Connection": "keep-alive",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /chat/history/{thread_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/history/{thread_id}")
async def get_chat_history(
    thread_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    Returns the full conversation history for a given thread.
    Only human and AI messages are returned (tool messages are hidden).
    """
    graph = request.app.state.chat_graph
    if graph is None:
        raise HTTPException(500, "Chatbot graph not initialised")

    config = {"configurable": {"thread_id": thread_id}}

    try:
        state = await graph.aget_state(config)
        messages = state.values.get("messages", [])
    except Exception as e:
        logger.opt(exception=True).error("History fetch error: {}", e)
        raise HTTPException(500, "Could not retrieve chat history")

    visible = [
        _serialise_message(m)
        for m in messages
        if isinstance(m, (HumanMessage, AIMessage))
        and not getattr(m, "tool_calls", None)
    ]

    return {"thread_id": thread_id, "messages": visible}


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /chat/history/{thread_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/history/{thread_id}")
async def clear_chat_history(
    thread_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    Clears the short-term memory (chat history) for a given thread.
    After calling this, the conversation starts fresh.
    """
    graph = request.app.state.chat_graph
    if graph is None:
        raise HTTPException(500, "Chatbot graph not initialised")

    config = {"configurable": {"thread_id": thread_id}}

    try:
        # Overwrite state with empty messages
        await graph.aupdate_state(config, {"messages": [], "in_scope": True})
    except Exception as e:
        logger.opt(exception=True).error("History clear error: {}", e)
        raise HTTPException(500, "Could not clear chat history")

    return {"message": f"Chat history for thread '{thread_id}' cleared."}