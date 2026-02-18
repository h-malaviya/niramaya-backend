# """
# chat_graph.py
# ─────────────
# LangGraph graph for the medical appointment chatbot.

# Nodes
# ─────
#   guard_node      →  Checks if user message is in-scope (appointment / doctor related).
#                      If out-of-scope → returns a polite static reply immediately.
#   agent_node      →  Calls GPT-4 with full tool-calling capability.
#                      If the model decides to call a tool → routes to tool_executor_node.
#                      Otherwise → END (streams final reply).
#   tool_executor_node → Runs the requested tool, appends ToolMessage, loops back to agent.

# State keys used
# ───────────────
#   messages        list[BaseMessage]
#   in_scope        bool
#   user_id         str
#   thread_id       str

# Flow
# ────
#   START → guard_node
#             ├─ out of scope → END (with static reply appended to messages)
#             └─ in scope     → agent_node
#                                 ├─ tool call → tool_executor_node → agent_node (loop)
#                                 └─ final reply → END
# """

# from __future__ import annotations

# import json
# import re
# from typing import Any, Literal

# from langchain_core.messages import (
#     AIMessage,
#     BaseMessage,
#     HumanMessage,
#     SystemMessage,
#     ToolMessage,
# )
# import os
# from langchain_openrouter import ChatOpenRouter
# from langgraph.graph import END, START, StateGraph
# from langgraph.graph.message import add_messages
# from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
# from typing_extensions import TypedDict, Annotated
# from langchain_groq import ChatGroq
# from services.chat_tools import ALL_TOOLS, set_tool_context
# from schemas.schemas import User
# from sqlalchemy.ext.asyncio import AsyncSession


# # ─────────────────────────────────────────────────────────────────────────────
# # Helpers
# # ─────────────────────────────────────────────────────────────────────────────

# def _content_to_text(content: Any) -> str:
#     """
#     LangChain message content can be a string OR a list of blocks like:
#       [{"type": "text", "text": "hello"}]
#     Normalise to a plain string for deterministic checks.
#     """
#     if content is None:
#         return ""
#     if isinstance(content, str):
#         return content
#     if isinstance(content, list):
#         parts: list[str] = []
#         for block in content:
#             if isinstance(block, dict):
#                 parts.append(str(block.get("text", "")))
#             else:
#                 parts.append(str(block))
#         return "".join(parts)
#     return str(content)


# # ─────────────────────────────────────────────────────────────────────────────
# # State definition
# # ─────────────────────────────────────────────────────────────────────────────

# class ChatState(TypedDict):
#     messages: Annotated[list[BaseMessage], add_messages]
#     in_scope: bool
#     user_id: str
#     thread_id: str

# MAX_CONTEXT_MESSAGES = 20
# # ─────────────────────────────────────────────────────────────────────────────
# # OpenRouter LLM factory
# # ChatOpenAI works with OpenRouter by overriding base_url + api_key.
# # Set OPENROUTER_API_KEY in your .env file.
# # ─────────────────────────────────────────────────────────────────────────────

# def _make_llm(streaming: bool = False, temperature: float = 0) -> ChatOpenRouter:
#     return ChatOpenRouter(
#         model="meta-llama/llama-3.3-70b-instruct:free",
#         temperature=temperature,
#         streaming=streaming,
       
#     )


# # Guard LLM – cheap, fast, no tools
# # _guard_llm = _make_llm(streaming=False, temperature=0)
# _GROQ_GUARD_MODEL = os.getenv("GROQ_GUARD_MODEL", "llama-3.1-8b-instant")
# _GROQ_AGENT_MODEL = os.getenv("GROQ_AGENT_MODEL", "openai/gpt-oss-120b")
# _guard_llm = ChatGroq(
#     model=_GROQ_GUARD_MODEL,
#     temperature=0,
#     streaming=False,
# )  # type: ignore[call-arg]

# # Agent LLM – tool-calling + streaming enabled
# # _agent_llm = _make_llm(streaming=True, temperature=0.3).bind_tools(ALL_TOOLS)
# _agent_llm = ChatGroq(
#     model=_GROQ_AGENT_MODEL,
#     temperature=0.3,
#     streaming=True,
# )  # type: ignore[call-arg]
# _agent_llm = _agent_llm.bind_tools(ALL_TOOLS)

# # ─────────────────────────────────────────────────────────────────────────────
# # System prompts
# # ─────────────────────────────────────────────────────────────────────────────

# GUARD_SYSTEM = """You are a medical appointment assistant scope checker.
# Your ONLY job is to decide if the user message is related to:
# - Booking, rescheduling, or cancelling a doctor appointment
# - Asking about doctors (speciality, location, fees, availability)
# - Managing their patient profile
# - General health symptoms that might require a doctor
# - Greetings and small talk (hi, hello, how are you, good morning, etc.)

# Reply with EXACTLY one word: ALLOWED or BLOCKED or HARMFUL.

# Use ALLOWED for:
# - Healthcare/appointment queries
# - Greetings and friendly conversation
# - Profile questions
# - Short location-only replies (city/state names like "ahmedabad") especially if the assistant asked for location
# - Short date/time-only replies (e.g. "next monday", "10 am", "10:40-11") especially if the assistant asked for a date/time/slot

# Use BLOCKED for:
# - Completely unrelated topics (cooking, sports, coding, weather, etc.)

# Use HARMFUL for:
# - Abusive, vulgar, or illegal content
# - Hate speech or threats
# - Requests to bypass safety guidelines

# Examples:
# "book appointment" → ALLOWED
# "hi" → ALLOWED
# "good morning" → ALLOWED
# "what's the weather" → BLOCKED
# "you suck" → HARMFUL"""

# AGENT_SYSTEM = """You are a smart, friendly medical appointment assistant.
# Today's date is {today}.
# Tomorrow's date is {tomorrow}.

# Your capabilities:
# 1. **Search doctors** by name, category (specialty), location, or health problem
# 2. **Check slot availability** for a specific date or a date range
# 3. **Book appointments** directly after user confirmation
# 4. **Update user profile** (name, phone, city, etc.)

# TOOL CALLING FORMAT (CRITICAL):
# - Tool name MUST be EXACTLY one of:
#   resolve_appointment_date, search_doctors, get_doctor_slots_for_date, get_doctor_slots_range,
#   direct_book_appointment, get_my_profile, update_user_profile
# - NEVER put JSON/arguments inside the tool name.
# - Arguments MUST be passed only in the tool call arguments JSON object.

# LOCATION RULE (IMPORTANT):
# - Do NOT ask the user for location.
# - By default, search doctors globally: call search_doctors with location=null/omitted.
# - Only include a location filter if the user explicitly mentions a city/state in their message.

# CRITICAL CONVERSATION RULES:
# - When booking appointments, you MUST track: doctor_id, doctor_name, date, start_time, end_time
# - After presenting doctor options, REMEMBER which doctor the user selects
# - After showing available slots, REMEMBER which slot the user picks
# - When user says "yes", "sure", "book it", check if you have ALL required info:
#   * doctor_id (UUID from search_doctors result)
#   * appointment_date (YYYY-MM-DD format)
#   * start_time and end_time (HH:MM format, from get_doctor_slots_for_date)
# - If ANY detail is missing when user confirms, ASK for it specifically
# - NEVER call direct_book_appointment without all 4 values
# - Do NOT treat a time string (e.g. "10:40-11", "10 am") as confirmation. Only explicit confirmation words count.

# Booking workflow:
# 1. User describes problem → search_doctors with appropriate category
# 2. Present options → user picks one → STORE doctor_id and doctor_name
# 3. Ask "which date?" → user replies → call get_doctor_slots_for_date
# 4. Show available slots → user picks one → STORE start_time and end_time
# 5. Show summary with ALL details → ask for confirmation
# 6. User confirms → call direct_book_appointment with stored values

# Date handling:
# - "next Monday" means the coming Monday (calculate from {today})
# - "tomorrow" means {tomorrow}
# - Always convert relative dates to YYYY-MM-DD before calling tools
# - For ANY relative date/weekday phrases ("tomorrow", "next monday", "monday"), call the tool resolve_appointment_date(text=<user_input>, today=<YYYY-MM-DD of today>) and use its appointment_date result.
# - When showing slots, always include the correct day of week with the date
# - Verify your day-of-week calculation is correct

# Other rules:
# - Ask for missing info ONE STEP AT A TIME (don't dump all questions at once)
# - If the requested date has no availability, call get_doctor_slots_range to suggest nearest dates
# - If the requested time slot is taken, suggest other available slots
# - When user describes a health problem, map symptoms to the correct category
# - Always respond in a warm, professional, concise manner
# - Never reveal raw UUIDs to the user
# - Slot times must always be presented in 12-hour format with AM/PM
# - If user provides only a start time (e.g. "10:40" or "10:40 am"), match it to an available slot's start_time from get_doctor_slots_for_date and use that slot's end_time. Do NOT ask the user for an end time if slots are fixed-duration.

# Category values you can use in search_doctors:
# family_physician, pediatrician, internist, geriatrician, cardiologist,
# dermatologist, endocrinologist, gastroenterologist, neurologist, oncologist,
# obstetrician_gynecologist, psychiatrist, pulmonologist, rheumatologist,
# nephrologist, allergist_immunologist, general_surgeon, orthopedic_surgeon,
# neurosurgeon, ophthalmologist, ent, urologist"""

# OUT_OF_SCOPE_REPLY = (
#     "I'm your medical appointment assistant — I can help you find doctors, "
#     "check availability, and book appointments. For anything outside healthcare "
#     "and appointments, I'm unable to help. Is there anything health-related I can assist you with?"
# )

# HARMFUL_REPLY = (
#     "I'm here to assist with healthcare and appointments in a respectful manner. "
#     "I cannot respond to harmful, abusive, or inappropriate content. "
#     "How can I help you with your health needs today?"
# )


# # ─────────────────────────────────────────────────────────────────────────────
# # Tool executor (maps tool name → function and runs it)
# # ─────────────────────────────────────────────────────────────────────────────

# _tool_map = {t.name: t for t in ALL_TOOLS}


# async def _run_tool(tool_name: str, tool_args: dict) -> str:
#     """Execute a tool by name and return its JSON-serialised result."""
#     fn = _tool_map.get(tool_name)
#     if not fn:
#         return json.dumps({"error": f"Unknown tool: {tool_name}"})
#     try:
#         result = await fn.ainvoke(tool_args)
#         return json.dumps(result, default=str)
#     except Exception as e:
#         return json.dumps({"error": str(e)})


# # ─────────────────────────────────────────────────────────────────────────────
# # Graph nodes
# # ─────────────────────────────────────────────────────────────────────────────

# async def guard_node(state: ChatState) -> dict:
#     """
#     Scope-check node with three outcomes: ALLOWED, BLOCKED, HARMFUL.
#     """
#     recent_messages = state["messages"][-5:]

#     # ── Deterministic overrides ──────────────────────────────────────────────
#     # Guard misclassification can break conversation when the user replies with
#     # short fragments (city names, "next monday", punctuation) that are clearly
#     # in-scope in context (answering a prior question).
#     last_user_msg = next((m for m in reversed(recent_messages) if isinstance(m, HumanMessage)), None)
#     last_ai_msg = next((m for m in reversed(recent_messages) if isinstance(m, AIMessage)), None)

#     user_text = _content_to_text(last_user_msg.content).strip() if last_user_msg else ""
#     ai_text = _content_to_text(last_ai_msg.content).lower() if last_ai_msg else ""

#     if user_text:
#         # Punctuation-only / very low-signal: let agent handle it (clarify)
#         if re.fullmatch(r"[.?!,;:\-_\s]+", user_text):
#             return {"in_scope": True}

#         # If assistant just asked for a booking input, allow short answers
#         ai_asked_for_booking_input = any(
#             phrase in ai_text
#             for phrase in (
#                 "which city",
#                 "which area",
#                 "your location",
#                 "tell me your location",
#                 "which date",
#                 "what date",
#                 "provide a date",
#                 "time slot",
#                 "slot number",
#                 "which time",
#                 "start time",
#                 "end time",
#             )
#         )

#         # Allow short "city-like" fragments (avoid blocking "ahmedabad")
#         # but do not override for clearly blocked keywords.
#         blocked_keywords = ("weather", "forecast", "temperature", "crypto", "bitcoin", "stocks", "trading")
#         looks_city_like = (
#             len(user_text) <= 40
#             and re.fullmatch(r"[A-Za-z][A-Za-z .'\-]{1,39}", user_text) is not None
#             and not any(k in user_text.lower() for k in blocked_keywords)
#         )

#         looks_date_time_like = (
#             len(user_text) <= 40
#             and any(tok in user_text.lower() for tok in ("tomorrow", "next", "am", "pm", ":", "-", "/"))
#             and not any(k in user_text.lower() for k in blocked_keywords)
#         )

#         if ai_asked_for_booking_input and (looks_city_like or looks_date_time_like):
#             return {"in_scope": True}

#         # Even without an explicit question, a city-only message is plausibly
#         # appointment-related; prefer ALLOWED to avoid derailing the chat.
#         if looks_city_like:
#             return {"in_scope": True}
    
#     # We format them simply for the Guard LLM
#     conversation_str = ""
#     for m in recent_messages:
#         role = "User" if isinstance(m, HumanMessage) else "Bot"
#         conversation_str += f"{role}: {m.content}\n"

#     response = await _guard_llm.ainvoke(
#         [
#             SystemMessage(content=GUARD_SYSTEM),
#             HumanMessage(content=f"Analyze this conversation context and the last user messages:\n\n{conversation_str}"),
#         ],
#         config={"tags": ["guard"]},
#     )

#     # Extract content safely - OpenRouter may return list or string
#     content = response.content
#     if isinstance(content, list):
#         # content is like [{"type": "text", "text": "ALLOWED"}]
#         verdict_text: str = ""
#         for block in content:
#             if isinstance(block, dict) and "text" in block:
#                 verdict_text = str(block["text"])
#                 break
#     else:
#         verdict_text = str(content)
    
#     verdict = verdict_text.strip().upper()
    
#     if verdict == "HARMFUL":
#         return {
#             "in_scope": False,
#             "messages": [AIMessage(content=HARMFUL_REPLY)],
#         }
    
#     if verdict == "BLOCKED":
#         return {
#             "in_scope": False,
#             "messages": [AIMessage(content=OUT_OF_SCOPE_REPLY)],
#         }

#     # ALLOWED or anything else → proceed to agent
#     return {"in_scope": True}


# async def agent_node(state: ChatState) -> dict:
#     """
#     Main LLM agent node.
#     Calls GPT-4 with tool bindings.  If the model emits tool_calls,
#     the router will send us to tool_executor_node.
#     """
#     from datetime import date as _date, timedelta
#     today = _date.today()
#     tomorrow = today + timedelta(days=1)
#     recent_messages = state["messages"][-MAX_CONTEXT_MESSAGES:]
#     system = AGENT_SYSTEM.format(
#         today=today.strftime("%Y-%m-%d (%A)"),       # "2026-02-18 (Wednesday)"
#         tomorrow=tomorrow.strftime("%Y-%m-%d (%A)")  # "2026-02-19 (Thursday)"
#     )
#     messages = [SystemMessage(content=system)] + recent_messages
#     response = await _agent_llm.ainvoke(messages)
#     return {"messages": [response]}


# async def tool_executor_node(state: ChatState) -> dict:
#     """
#     Executes all tool calls in the last AIMessage and appends ToolMessages.
#     """
#     last_ai: AIMessage = state["messages"][-1]  # type: ignore
#     tool_messages = []

#     def _is_explicit_confirmation(text: Any) -> bool:
#         t = _content_to_text(text).strip().lower()
#         if not t:
#             return False
#         # single-word confirmations
#         if t in {"yes", "y", "yeah", "yep", "sure", "ok", "okay", "confirm"}:
#             return True
#         # common phrases
#         phrases = (
#             "book it",
#             "go for it",
#             "let's do it",
#             "lets do it",
#             "proceed",
#             "go ahead",
#             "sounds good",
#             "that works",
#             "yes please",
#             "please book",
#         )
#         return any(p in t for p in phrases)

#     last_human = next((m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), None)
#     last_human_text = _content_to_text(last_human.content) if last_human else ""

#     for tool_call in last_ai.tool_calls:
#         # Hard safety gate: don't allow booking unless user explicitly confirmed.
#         if tool_call["name"] == "direct_book_appointment" and not _is_explicit_confirmation(last_human_text):
#             tool_messages.append(
#                 ToolMessage(
#                     content=json.dumps(
#                         {
#                             "error": "booking_not_confirmed",
#                             "message": "User did not explicitly confirm booking. Ask for confirmation (yes/no) before booking.",
#                         }
#                     ),
#                     tool_call_id=tool_call["id"],
#                     name=tool_call["name"],
#                 )
#             )
#             continue

#         result_str = await _run_tool(tool_call["name"], tool_call["args"])
#         tool_messages.append(
#             ToolMessage(
#                 content=result_str,
#                 tool_call_id=tool_call["id"],
#                 name=tool_call["name"],
#             )
#         )

#     return {"messages": tool_messages}


# # ─────────────────────────────────────────────────────────────────────────────
# # Conditional edge functions
# # ─────────────────────────────────────────────────────────────────────────────

# def route_after_guard(state: ChatState) -> Literal["agent_node", "__end__"]:
#     """After guard: go to agent if in-scope, otherwise end."""
#     return "agent_node" if state.get("in_scope", True) else "__end__"


# def route_after_agent(state: ChatState) -> Literal["tool_executor_node", "__end__"]:
#     """After agent: go to tool executor if there are tool calls, otherwise end."""
#     last = state["messages"][-1]
#     if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
#         return "tool_executor_node"
#     return "__end__"


# # ─────────────────────────────────────────────────────────────────────────────
# # Graph builder
# # ─────────────────────────────────────────────────────────────────────────────

# def build_graph(checkpointer: AsyncSqliteSaver) -> Any:
#     """
#     Build and compile the LangGraph StateGraph.
#     Call once at application startup; reuse for all requests.
#     """
#     builder = StateGraph(ChatState)

#     builder.add_node("guard_node", guard_node)
#     builder.add_node("agent_node", agent_node)
#     builder.add_node("tool_executor_node", tool_executor_node)

#     builder.add_edge(START, "guard_node")
#     builder.add_conditional_edges("guard_node", route_after_guard)
#     builder.add_conditional_edges("agent_node", route_after_agent)
#     builder.add_edge("tool_executor_node", "agent_node")  # loop back after tool

#     return builder.compile(checkpointer=checkpointer)

from __future__ import annotations

import json
import re
from typing import Any, Literal

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
import os
from langchain_openrouter import ChatOpenRouter
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from typing_extensions import TypedDict, Annotated
from langchain_groq import ChatGroq
from services.chat_tools import ALL_TOOLS, set_tool_context
from schemas.schemas import User
from sqlalchemy.ext.asyncio import AsyncSession


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _content_to_text(content: Any) -> str:
    """
    LangChain message content can be a string OR a list of blocks like:
      [{"type": "text", "text": "hello"}]
    Normalise to a plain string for deterministic checks.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


# ─────────────────────────────────────────────────────────────────────────────
# State definition
# ─────────────────────────────────────────────────────────────────────────────

class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    in_scope: bool
    user_id: str
    thread_id: str

MAX_CONTEXT_MESSAGES = 20
# ─────────────────────────────────────────────────────────────────────────────
# OpenRouter LLM factory
# ChatOpenAI works with OpenRouter by overriding base_url + api_key.
# Set OPENROUTER_API_KEY in your .env file.
# ─────────────────────────────────────────────────────────────────────────────

def _make_llm(streaming: bool = False, temperature: float = 0) -> ChatOpenRouter:
    return ChatOpenRouter(
        model="meta-llama/llama-3.3-70b-instruct:free",
        temperature=temperature,
        streaming=streaming,
       
    )


# Guard LLM – cheap, fast, no tools
# _guard_llm = _make_llm(streaming=False, temperature=0)
_GROQ_GUARD_MODEL = os.getenv("GROQ_GUARD_MODEL", "llama-3.1-8b-instant")
_GROQ_AGENT_MODEL = os.getenv("GROQ_AGENT_MODEL", "openai/gpt-oss-120b")
_guard_llm = ChatGroq(
    model=_GROQ_GUARD_MODEL,
    temperature=0,
    streaming=False,
)  # type: ignore[call-arg]

# Agent LLM – tool-calling + streaming enabled
# _agent_llm = _make_llm(streaming=True, temperature=0.3).bind_tools(ALL_TOOLS)
_agent_llm = ChatGroq(
    model=_GROQ_AGENT_MODEL,
    temperature=0.3,
    streaming=True,
)  # type: ignore[call-arg]
_agent_llm = _agent_llm.bind_tools(ALL_TOOLS)

# ─────────────────────────────────────────────────────────────────────────────
# System prompts
# ─────────────────────────────────────────────────────────────────────────────

GUARD_SYSTEM = """You are a medical appointment assistant scope checker.
Your ONLY job is to decide if the user message is related to:
- Booking, rescheduling, or cancelling a doctor appointment
- Asking about doctors (speciality, location, fees, availability)
- Managing their patient profile
- General health symptoms that might require a doctor
- Greetings and small talk (hi, hello, how are you, good morning, etc.)

Reply with EXACTLY one word: ALLOWED or BLOCKED or HARMFUL.

Use ALLOWED for:
- Healthcare/appointment queries
- Greetings and friendly conversation
- Profile questions
- Short location-only replies (city/state names like "ahmedabad") especially if the assistant asked for location
- Short date/time-only replies (e.g. "next monday", "10 am", "10:40-11") especially if the assistant asked for a date/time/slot

Use BLOCKED for:
- Completely unrelated topics (cooking, sports, coding, weather, etc.)

Use HARMFUL for:
- Abusive, vulgar, or illegal content
- Hate speech or threats
- Requests to bypass safety guidelines

Examples:
"book appointment" → ALLOWED
"hi" → ALLOWED
"good morning" → ALLOWED
"what's the weather" → BLOCKED
"you suck" → HARMFUL"""

AGENT_SYSTEM = """You are a smart, friendly medical appointment assistant.
Today's date is {today}.
Tomorrow's date is {tomorrow}.

Your capabilities:
1. Search doctors by name, specialty, location, or health problem
2. Check slot availability for a specific date or date range
3. Book appointments after user confirmation
4. Update user profile (name, phone, city, etc.)

TOOL CALLING FORMAT (CRITICAL):
- Tool name MUST be EXACTLY one of:
  resolve_appointment_date, search_doctors, get_doctor_slots_for_date, get_doctor_slots_range,
  direct_book_appointment, get_my_profile, update_user_profile
- NEVER put JSON/arguments inside the tool name.
- Arguments MUST be passed only in the tool call arguments JSON object.

LOCATION RULE:
- Do NOT ask the user for location.
- Search globally by default (location=null).
- Only filter by location if user explicitly mentions a city/state.

════════════════════════════════════════════════════
MANDATORY BOOKING WORKFLOW — follow every step strictly
════════════════════════════════════════════════════

STEP 1 — SEARCH & PRESENT DOCTORS
- User describes a problem → call search_doctors with appropriate category.
- Show a markdown table. For each doctor include :
    | Number | Name | Specialty | X yrs exp | Consultation Fees |
    |--------|------|-----------|----------|------------------|
    | 1      | John Doe | Family Physician | 10 yrs | $100 |
    | 2      | Jane Smith | Cardiologist | 5 yrs | $200 |
    | 3      | Jim Beam | Neurologist | 8 yrs | $150 |
    | ...    | ...      | ...         | ...      | ...      |
- Ask: "Which doctor would you like? (reply with number or name)"

STEP 2 — STORE DOCTOR & ASK FOR DATE
- User picks a doctor → store doctor_id and doctor_name.
- Ask ONLY: "Which date would you like the appointment?"
- Do NOT ask for time yet.

STEP 3 — RESOLVE DATE
- For any relative date ("tomorrow", "next monday", "upcoming tuesday", bare weekday) call resolve_appointment_date first, then use its appointment_date result.

STEP 4 — ASK FOR TIME PREFERENCE ← YOU MUST DO THIS BEFORE FETCHING SLOTS
- After the date is confirmed, you MUST ask:
  "What time works best for you — morning (before 12 PM), afternoon (12–5 PM), or evening (after 5 PM)? Or mention a specific time like 10:30 AM."
- DO NOT call get_doctor_slots_for_date yet.
- DO NOT show any slots yet.
- WAIT for the user's reply.

STEP 5 — FETCH SLOTS & FILTER BY PREFERENCE
- Only AFTER the user replies to the time preference question, call get_doctor_slots_for_date.
- Filter the results using the "period" field on each slot:
    * morning   → period == "morning"   (before 12 PM)
    * afternoon → period == "afternoon" (12 PM – 5 PM)
    * evening   → period == "evening"   (after 5 PM)
    * specific time (e.g. "10:30 AM") → show the 3–4 slots closest to that time
    * "all" or "any" or "show all" → show all available slots
- Show ONLY available slots (state == "available"), max 8, numbered in markdown table:
    | Number | Start Time | End Time |
    |--------|------------|----------|
    | 1      | 10:00 AM   | 10:20 AM |
    | 2      | 10:20 AM   | 10:40 AM |
- If NO available slots in the requested period, say so and ask if they want a different period or date.
- Ask: "Which slot do you prefer? (reply with number or start time)"

STEP 6 — HANDLE SLOT SELECTION
- User picks by NUMBER → use the slot at that position in your displayed list.
- User picks by START TIME (e.g. "10:20" or "10:20 AM") → match to that start_time.
- Store the chosen start_time and end_time.

STEP 7 — HANDLE BOOKED / UNAVAILABLE SLOT
- If chosen slot is not "available":
    a. Suggest the next available slot on the SAME date (if any).
    b. If none, suggest same period on the next available date via get_doctor_slots_range.
    c. Present ONE alternative at a time.

STEP 8 — BOOKING SUMMARY & CONFIRMATION
- Show a summary in markdown table:
    | Doctor Name | Doctor Speciality | Date | Time |
    |--------|-----------|----------|----------|
    | [doctor_name] | [doctor_specialty] | [day], [date] | [start] – [end] |
  Then ask: "Reply yes to confirm or no to change something."
- WAIT for explicit confirmation: yes / sure / confirm / go ahead / book it.

STEP 9 — BOOK THE APPOINTMENT
- ONLY after explicit confirmation call direct_book_appointment.
- On success: confirm warmly.
- On failure (slot taken): apologise then go to STEP 7.

════════════════════════════════════════════════════
OTHER RULES
════════════════════════════════════════════════════
- ONE question at a time — never ask for date and time together.
- Never reveal raw UUIDs.
- Always show times in 12-hour AM/PM format.
- Always show day-of-week with the date.
- Map symptoms to the correct specialty before searching.
- Respond warmly, concisely, and professionally.

Category values for search_doctors:
family_physician, pediatrician, internist, geriatrician, cardiologist,
dermatologist, endocrinologist, gastroenterologist, neurologist, oncologist,
obstetrician_gynecologist, psychiatrist, pulmonologist, rheumatologist,
nephrologist, allergist_immunologist, general_surgeon, orthopedic_surgeon,
neurosurgeon, ophthalmologist, ent, urologist"""

OUT_OF_SCOPE_REPLY = (
    "I'm your medical appointment assistant — I can help you find doctors, "
    "check availability, and book appointments. For anything outside healthcare "
    "and appointments, I'm unable to help. Is there anything health-related I can assist you with?"
)

HARMFUL_REPLY = (
    "I'm here to assist with healthcare and appointments in a respectful manner. "
    "I cannot respond to harmful, abusive, or inappropriate content. "
    "How can I help you with your health needs today?"
)


# ─────────────────────────────────────────────────────────────────────────────
# Tool executor (maps tool name → function and runs it)
# ─────────────────────────────────────────────────────────────────────────────

_tool_map = {t.name: t for t in ALL_TOOLS}


async def _run_tool(tool_name: str, tool_args: dict) -> str:
    """Execute a tool by name and return its JSON-serialised result."""
    fn = _tool_map.get(tool_name)
    if not fn:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    try:
        result = await fn.ainvoke(tool_args)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Graph nodes
# ─────────────────────────────────────────────────────────────────────────────

async def guard_node(state: ChatState) -> dict:
    """
    Scope-check node with three outcomes: ALLOWED, BLOCKED, HARMFUL.
    """
    recent_messages = state["messages"][-5:]

    # ── Deterministic overrides ──────────────────────────────────────────────
    # Guard misclassification can break conversation when the user replies with
    # short fragments (city names, "next monday", punctuation) that are clearly
    # in-scope in context (answering a prior question).
    last_user_msg = next((m for m in reversed(recent_messages) if isinstance(m, HumanMessage)), None)
    last_ai_msg = next((m for m in reversed(recent_messages) if isinstance(m, AIMessage)), None)

    user_text = _content_to_text(last_user_msg.content).strip() if last_user_msg else ""
    ai_text = _content_to_text(last_ai_msg.content).lower() if last_ai_msg else ""

    if user_text:
        # Punctuation-only / very low-signal: let agent handle it (clarify)
        if re.fullmatch(r"[.?!,;:\-_\s]+", user_text):
            return {"in_scope": True}

        # If assistant just asked for a booking input, allow short answers
        ai_asked_for_booking_input = any(
            phrase in ai_text
            for phrase in (
                "which city",
                "which area",
                "your location",
                "tell me your location",
                "which date",
                "what date",
                "provide a date",
                "time slot",
                "slot number",
                "which slot",
                "which time",
                "start time",
                "end time",
                "morning",
                "afternoon",
                "evening",
                "time works best",
                "which doctor",
                "doctor would you like",
                "reply with number",
            )
        )

        # Allow short "city-like" fragments (avoid blocking "ahmedabad")
        # but do not override for clearly blocked keywords.
        blocked_keywords = ("weather", "forecast", "temperature", "crypto", "bitcoin", "stocks", "trading")
        looks_city_like = (
            len(user_text) <= 40
            and re.fullmatch(r"[A-Za-z][A-Za-z .\'\-]{1,39}", user_text) is not None
            and not any(k in user_text.lower() for k in blocked_keywords)
        )

        looks_date_time_like = (
            len(user_text) <= 40
            and any(tok in user_text.lower() for tok in ("tomorrow", "next", "upcoming", "coming", "this", "following", "am", "pm", ":", "-", "/"))
            and not any(k in user_text.lower() for k in blocked_keywords)
        )

        # Allow period keywords and slot number replies
        looks_period_or_slot = (
            len(user_text) <= 20
            and any(tok in user_text.lower() for tok in ("morning", "afternoon", "evening"))
        )

        looks_number_reply = (
            len(user_text) <= 5
            and re.fullmatch(r"\d{1,2}", user_text.strip()) is not None
        )

        if ai_asked_for_booking_input and (
            looks_city_like or looks_date_time_like or looks_period_or_slot or looks_number_reply
        ):
            return {"in_scope": True}

        # Even without an explicit question, a city-only message is plausibly
        # appointment-related; prefer ALLOWED to avoid derailing the chat.
        if looks_city_like:
            return {"in_scope": True}
    
    # We format them simply for the Guard LLM
    conversation_str = ""
    for m in recent_messages:
        role = "User" if isinstance(m, HumanMessage) else "Bot"
        conversation_str += f"{role}: {m.content}\n"

    response = await _guard_llm.ainvoke(
        [
            SystemMessage(content=GUARD_SYSTEM),
            HumanMessage(content=f"Analyze this conversation context and the last user messages:\n\n{conversation_str}"),
        ],
        config={"tags": ["guard"]},
    )

    # Extract content safely - OpenRouter may return list or string
    content = response.content
    if isinstance(content, list):
        # content is like [{"type": "text", "text": "ALLOWED"}]
        verdict_text: str = ""
        for block in content:
            if isinstance(block, dict) and "text" in block:
                verdict_text = str(block["text"])
                break
    else:
        verdict_text = str(content)
    
    verdict = verdict_text.strip().upper()
    
    if verdict == "HARMFUL":
        return {
            "in_scope": False,
            "messages": [AIMessage(content=HARMFUL_REPLY)],
        }
    
    if verdict == "BLOCKED":
        return {
            "in_scope": False,
            "messages": [AIMessage(content=OUT_OF_SCOPE_REPLY)],
        }

    # ALLOWED or anything else → proceed to agent
    return {"in_scope": True}


async def agent_node(state: ChatState) -> dict:
    """
    Main LLM agent node.
    Calls GPT-4 with tool bindings.  If the model emits tool_calls,
    the router will send us to tool_executor_node.
    """
    from datetime import date as _date, timedelta
    today = _date.today()
    tomorrow = today + timedelta(days=1)
    recent_messages = state["messages"][-MAX_CONTEXT_MESSAGES:]
    system = AGENT_SYSTEM.format(
        today=today.strftime("%Y-%m-%d (%A)"),       # "2026-02-18 (Wednesday)"
        tomorrow=tomorrow.strftime("%Y-%m-%d (%A)")  # "2026-02-19 (Thursday)"
    )
    messages = [SystemMessage(content=system)] + recent_messages
    response = await _agent_llm.ainvoke(messages)
    return {"messages": [response]}


async def tool_executor_node(state: ChatState) -> dict:
    """
    Executes all tool calls in the last AIMessage and appends ToolMessages.
    """
    last_ai: AIMessage = state["messages"][-1]  # type: ignore
    tool_messages = []

    def _is_explicit_confirmation(text: Any) -> bool:
        t = _content_to_text(text).strip().lower()
        if not t:
            return False
        # single-word confirmations
        if t in {"yes", "y", "yeah", "yep", "sure", "ok", "okay", "confirm"}:
            return True
        # common phrases
        phrases = (
            "book it",
            "go for it",
            "let's do it",
            "lets do it",
            "proceed",
            "go ahead",
            "sounds good",
            "that works",
            "yes please",
            "please book",
        )
        return any(p in t for p in phrases)

    last_human = next((m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), None)
    last_human_text = _content_to_text(last_human.content) if last_human else ""

    for tool_call in last_ai.tool_calls:
        # Hard safety gate: don't allow booking unless user explicitly confirmed.
        if tool_call["name"] == "direct_book_appointment" and not _is_explicit_confirmation(last_human_text):
            tool_messages.append(
                ToolMessage(
                    content=json.dumps(
                        {
                            "error": "booking_not_confirmed",
                            "message": "User did not explicitly confirm booking. Ask for confirmation (yes/no) before booking.",
                        }
                    ),
                    tool_call_id=tool_call["id"],
                    name=tool_call["name"],
                )
            )
            continue

        result_str = await _run_tool(tool_call["name"], tool_call["args"])
        tool_messages.append(
            ToolMessage(
                content=result_str,
                tool_call_id=tool_call["id"],
                name=tool_call["name"],
            )
        )

    return {"messages": tool_messages}


# ─────────────────────────────────────────────────────────────────────────────
# Conditional edge functions
# ─────────────────────────────────────────────────────────────────────────────

def route_after_guard(state: ChatState) -> Literal["agent_node", "__end__"]:
    """After guard: go to agent if in-scope, otherwise end."""
    return "agent_node" if state.get("in_scope", True) else "__end__"


def route_after_agent(state: ChatState) -> Literal["tool_executor_node", "__end__"]:
    """After agent: go to tool executor if there are tool calls, otherwise end."""
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
        return "tool_executor_node"
    return "__end__"


# ─────────────────────────────────────────────────────────────────────────────
# Graph builder
# ─────────────────────────────────────────────────────────────────────────────

def build_graph(checkpointer: AsyncSqliteSaver) -> Any:
    """
    Build and compile the LangGraph StateGraph.
    Call once at application startup; reuse for all requests.
    """
    builder = StateGraph(ChatState)

    builder.add_node("guard_node", guard_node)
    builder.add_node("agent_node", agent_node)
    builder.add_node("tool_executor_node", tool_executor_node)

    builder.add_edge(START, "guard_node")
    builder.add_conditional_edges("guard_node", route_after_guard)
    builder.add_conditional_edges("agent_node", route_after_agent)
    builder.add_edge("tool_executor_node", "agent_node")  # loop back after tool

    return builder.compile(checkpointer=checkpointer)