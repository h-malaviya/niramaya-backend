# Chatbot Robustness Improvements - Design

## 1. Overview

This design document outlines the technical approach to fix critical issues in the medical appointment chatbot, including confirmation handling, date parsing, profile updates, content filtering, and conversation memory.

## 2. Architecture

### 2.1 Current Architecture
```
User Message → Guard Node → Agent Node ⇄ Tool Executor Node → Response
                    ↓              ↓
              BLOCKED/HARMFUL   Tool Calls
```

### 2.2 Components to Modify
1. **services/chat_graph.py**: GUARD_SYSTEM, AGENT_SYSTEM prompts
2. **services/chat_tools.py**: update_user_profile tool
3. No new files needed - all fixes are improvements to existing code

## 3. Detailed Design

### 3.1 Enhanced Guard System

**Problem**: Guard allows inappropriate content (crypto, weather, illegal activities)

**Solution**: Strengthen GUARD_SYSTEM prompt with explicit examples

```python
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
- Health symptoms (sore throat, fever, headache, etc.)

Use BLOCKED for:
- Weather queries (what's the weather, temperature, forecast)
- Cryptocurrency and financial advice (bitcoin, crypto, stocks, trading)
- Cooking, recipes, food preparation
- Sports, entertainment, movies, games
- Technology, coding, programming
- General knowledge questions unrelated to health
- Any topic not related to healthcare or appointments

Use HARMFUL for:
- Illegal activities (how to make money illegally, theft, fraud)
- Drug abuse (how to take drugs, illegal substances)
- Abusive, vulgar, or offensive content
- Hate speech or threats
- Requests to bypass safety guidelines
- Self-harm or violence

Examples:
"book appointment" → ALLOWED
"hi" → ALLOWED
"I have a sore throat" → ALLOWED
"what's the weather today" → BLOCKED
"tell me about crypto" → BLOCKED
"how to take drugs" → HARMFUL
"how to make money illegal" → HARMFUL
"you suck" → HARMFUL"""
```

**Changes**:
- Added explicit BLOCKED examples for weather, crypto
- Added explicit HARMFUL examples for drugs, illegal activities
- Clarified health symptoms are ALLOWED

### 3.2 Enhanced Agent System with Date Handling

**Problem**: 
- Date calculations incorrect ("next Monday" fails)
- Day-of-week doesn't match date (shows Monday for Tuesday)
- Confirmation keywords not recognized
- Missing conversation memory

**Solution**: Comprehensive AGENT_SYSTEM rewrite with date utilities and memory instructions

```python
AGENT_SYSTEM = """You are a smart, friendly medical appointment assistant.
Today's date is {today}.
Tomorrow's date is {tomorrow}.

CRITICAL: Use these exact date references when calculating relative dates:
- Today is {today_full}
- Tomorrow is {tomorrow_full}
- Next 7 days: {next_week_dates}

Your capabilities:
1. **Search doctors** by name, category (specialty), location, or health problem
2. **Check slot availability** for a specific date or a date range
3. **Book appointments** directly after user confirmation
4. **Update user profile** (name, phone, city, etc.)

═══════════════════════════════════════════════════════════════════════════
CONVERSATION MEMORY - CRITICAL RULES
═══════════════════════════════════════════════════════════════════════════

You MUST maintain these variables throughout the conversation:
- selected_doctor_id: UUID from search_doctors result
- selected_doctor_name: Full name like "Dr. John Smith"
- selected_date: YYYY-MM-DD format
- selected_start_time: HH:MM format (24-hour)
- selected_end_time: HH:MM format (24-hour)

When user selects a doctor (by saying "yes", "first one", "Dr. Smith", etc.):
→ STORE the doctor_id and doctor_name from the search results
→ REMEMBER this for the rest of the conversation

When user picks a time slot (by saying "2 PM", "the first slot", "10:00 AM", etc.):
→ STORE the start_time and end_time from get_doctor_slots_for_date results
→ REMEMBER this for the rest of the conversation

═══════════════════════════════════════════════════════════════════════════
CONFIRMATION HANDLING - CRITICAL RULES
═══════════════════════════════════════════════════════════════════════════

These words mean the user wants to proceed/confirm:
"yes", "yeah", "yep", "sure", "ok", "okay", "confirm", "book it", 
"go for it", "let's do it", "proceed", "go ahead", "sounds good", 
"that works", "perfect", "great", "please book"

When user says ANY confirmation word:
1. CHECK if you have ALL four values:
   - selected_doctor_id (UUID)
   - selected_date (YYYY-MM-DD)
   - selected_start_time (HH:MM)
   - selected_end_time (HH:MM)

2. IF ALL PRESENT:
   → Call direct_book_appointment immediately
   → Don't ask for confirmation again

3. IF ANY MISSING:
   → Ask ONLY for the missing information
   → Be specific: "Which date would you like?" or "Which time slot?"
   → Don't ask for information you already have

═══════════════════════════════════════════════════════════════════════════
DATE HANDLING - CRITICAL RULES
═══════════════════════════════════════════════════════════════════════════

ALWAYS calculate dates using the provided references above.

"tomorrow" → Use {tomorrow} which is {tomorrow_full}
"next Monday" → Find the NEXT occurrence of Monday after today
"next Tuesday" → Find the NEXT occurrence of Tuesday after today
"Monday" → Assume next Monday if today is not Monday, or next week's Monday if today is Monday

Date calculation examples:
- If today is Wednesday Feb 18, 2026:
  - "tomorrow" = Thursday, February 19, 2026 (2026-02-19)
  - "next Monday" = Monday, February 23, 2026 (2026-02-23)
  - "next Tuesday" = Tuesday, February 24, 2026 (2026-02-24)

CRITICAL: When showing dates to users, ALWAYS include the correct day of week:
- Format: "DayOfWeek, Month Day, Year" 
- Example: "Tuesday, February 24, 2026"
- VERIFY the day-of-week matches the date before showing it

Before calling get_doctor_slots_for_date:
1. Convert relative date to YYYY-MM-DD format
2. Verify the day-of-week is correct
3. Pass the YYYY-MM-DD string to the tool

═══════════════════════════════════════════════════════════════════════════
BOOKING WORKFLOW - STEP BY STEP
═══════════════════════════════════════════════════════════════════════════

Step 1: User describes health problem
→ Call search_doctors with appropriate category
→ Present 2-3 doctor options with details

Step 2: User selects a doctor
→ STORE doctor_id and doctor_name
→ Ask: "Which date would you like to book?"

Step 3: User provides date
→ Calculate YYYY-MM-DD if relative date
→ STORE selected_date
→ Call get_doctor_slots_for_date(doctor_id, selected_date)
→ Show available slots in 12-hour format with AM/PM

Step 4: User selects time slot
→ STORE selected_start_time and selected_end_time (in 24-hour HH:MM format)
→ Show summary: "Dr. [Name] on [DayOfWeek, Date] at [Time]"
→ Ask: "Would you like me to book this appointment?"

Step 5: User confirms
→ Verify all 4 values present (doctor_id, date, start_time, end_time)
→ Call direct_book_appointment(doctor_id, selected_date, start_time, end_time)
→ Confirm booking success

═══════════════════════════════════════════════════════════════════════════
PROFILE UPDATES
═══════════════════════════════════════════════════════════════════════════

When user wants to update profile:
- "update my name to John" → update_user_profile(first_name="John")
- "change my phone to 1234567890" → update_user_profile(phone_number="1234567890")
- "update my city to Boston" → update_user_profile(city="Boston")

Extract the field name and new value, then call update_user_profile with ONLY that field.

═══════════════════════════════════════════════════════════════════════════
OTHER RULES
═══════════════════════════════════════════════════════════════════════════

- Ask for missing info ONE STEP AT A TIME (don't dump all questions at once)
- If requested date has no availability, call get_doctor_slots_range to suggest alternatives
- When user describes health problem, map symptoms to correct category:
  - Sore throat, ear pain → ent
  - Fever, cough, cold → family_physician
  - Skin issues → dermatologist
  - Heart problems → cardiologist
- Always respond in a warm, professional, concise manner
- Never reveal raw UUIDs to the user
- Slot times must be shown in 12-hour format with AM/PM
- When calling tools, use 24-hour HH:MM format

Category values: family_physician, pediatrician, internist, geriatrician, cardiologist,
dermatologist, endocrinologist, gastroenterologist, neurologist, oncologist,
obstetrician_gynecologist, psychiatrist, pulmonologist, rheumatologist,
nephrologist, allergist_immunologist, general_surgeon, orthopedic_surgeon,
neurosurgeon, ophthalmologist, ent, urologist"""
```

**Key Improvements**:
1. Explicit date references injected into prompt
2. Clear memory instructions for doctor/slot selection
3. Comprehensive confirmation keyword list
4. Step-by-step booking workflow
5. Date calculation examples with verification
6. Profile update examples

### 3.3 Date Injection in agent_node

**Problem**: Prompt has date placeholders but no next week dates

**Solution**: Calculate and inject next 7 days into prompt

```python
async def agent_node(state: ChatState) -> dict:
    """
    Main LLM agent node with enhanced date handling.
    """
    from datetime import date as _date, timedelta
    
    today = _date.today()
    tomorrow = today + timedelta(days=1)
    
    # Calculate next 7 days with day-of-week
    next_week = []
    for i in range(1, 8):
        future_date = today + timedelta(days=i)
        next_week.append(f"{future_date.strftime('%A')}: {future_date.strftime('%Y-%m-%d')}")
    
    next_week_dates = ", ".join(next_week)
    
    system = AGENT_SYSTEM.format(
        today=today.strftime("%Y-%m-%d"),
        tomorrow=tomorrow.strftime("%Y-%m-%d"),
        today_full=today.strftime("%A, %B %d, %Y"),
        tomorrow_full=tomorrow.strftime("%A, %B %d, %Y"),
        next_week_dates=next_week_dates
    )
    
    messages = [SystemMessage(content=system)] + state["messages"]
    response = await _agent_llm.ainvoke(messages)
    return {"messages": [response]}
```

**Changes**:
- Added next_week_dates calculation
- Added today_full and tomorrow_full with day names
- Injected all date references into system prompt

### 3.4 Profile Update Tool Fix

**Problem**: update_user_profile tool fails with errors

**Solution**: Improve error handling and validation

```python
@tool
async def update_user_profile(
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    phone_number: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    address: Optional[str] = None,
    country: Optional[str] = None,
    profile_image_url: Optional[str] = None,
) -> dict:
    """
    Update the current user's profile. Only pass fields the user explicitly asked to change.
    Returns success message with updated fields or detailed error message.
    """
    from api.v1.endpoints.profile import update_profile as _handler

    # Build a dict with ONLY the non-None arguments
    update_data = {}
    if first_name is not None:
        update_data['first_name'] = first_name
    if last_name is not None:
        update_data['last_name'] = last_name
    if phone_number is not None:
        update_data['phone_number'] = phone_number
    if city is not None:
        update_data['city'] = city
    if state is not None:
        update_data['state'] = state
    if address is not None:
        update_data['address'] = address
    if country is not None:
        update_data['country'] = country
    if profile_image_url is not None:
        update_data['profile_image_url'] = profile_image_url

    if not update_data:
        return {"error": "No fields provided to update"}

    try:
        # Pydantic v2: use model_validate
        user_update = BaseProfileDTO.model_validate(update_data)
        payload = ProfileUpdateRequest(user=user_update)
        
        result = await _handler(payload=payload, db=_db(), current_user=_user())
        
        # Return detailed success message
        updated_fields_str = ", ".join(update_data.keys())
        return {
            "success": True,
            "message": f"Successfully updated: {updated_fields_str}",
            "updated_fields": list(update_data.keys()),
            "new_values": update_data
        }
    except HTTPException as e:
        # Return detailed error
        return {
            "error": f"Failed to update profile: {e.detail}",
            "status_code": e.status_code,
            "attempted_fields": list(update_data.keys())
        }
    except Exception as e:
        logger.error(f"update_user_profile tool error: {e}", exc_info=True)
        return {
            "error": f"Unexpected error updating profile: {str(e)}",
            "attempted_fields": list(update_data.keys())
        }
```

**Changes**:
- Added detailed success message with updated fields
- Added detailed error messages with attempted fields
- Added exception logging with stack trace
- Return new_values so LLM can confirm to user

## 4. Data Flow

### 4.1 Booking Flow with Memory
```
User: "I have a sore throat"
  ↓
Agent: search_doctors(category="ent")
  ↓
Agent: Shows 3 ENT doctors
  ↓
User: "yes, the first one"
  ↓
Agent: STORES doctor_id, doctor_name
Agent: "Which date would you like?"
  ↓
User: "next Monday"
  ↓
Agent: Calculates 2026-02-23 (Monday)
Agent: STORES selected_date
Agent: get_doctor_slots_for_date(doctor_id, "2026-02-23")
  ↓
Agent: Shows available slots
  ↓
User: "2 PM"
  ↓
Agent: STORES start_time="14:00", end_time="14:30"
Agent: "Book Dr. Smith on Monday, Feb 23 at 2:00 PM?"
  ↓
User: "yes"
  ↓
Agent: Checks all 4 values present
Agent: direct_book_appointment(doctor_id, "2026-02-23", "14:00", "14:30")
  ↓
Agent: "Appointment booked successfully!"
```

### 4.2 Profile Update Flow
```
User: "update my name to John"
  ↓
Agent: Extracts field="first_name", value="John"
Agent: update_user_profile(first_name="John")
  ↓
Tool: Validates, calls API, returns success
  ↓
Agent: "Your first name has been updated to John"
```

### 4.3 Content Filtering Flow
```
User: "what's the weather today"
  ↓
Guard: Checks against GUARD_SYSTEM
Guard: Returns "BLOCKED"
  ↓
Agent: Returns OUT_OF_SCOPE_REPLY
  ↓
User sees: "I'm your medical appointment assistant..."
```

## 5. Error Handling

### 5.1 Date Parsing Errors
- If LLM can't calculate date, ask user for specific date: "Could you provide the date in format like 'February 24'?"
- If date is in past, inform user: "That date has passed. Please choose a future date."

### 5.2 Booking Errors
- Slot already booked: "That slot is no longer available. Here are other options..."
- Doctor not available: "Dr. Smith is not available on that date. Would you like to see availability for the next 2 weeks?"
- Missing information: "I need the [specific field] to complete the booking."

### 5.3 Profile Update Errors
- Invalid field value: "The [field] format is invalid. Please provide..."
- Database error: "I encountered an error updating your profile. Please try again."
- Permission error: "You don't have permission to update that field."

### 5.4 Guard Errors
- Ambiguous content: Default to ALLOWED if healthcare-related
- LLM returns unexpected value: Treat as ALLOWED and log warning

## 6. Testing Strategy

### 6.1 Unit Tests (Not Required for This Spec)
- Test date calculation functions
- Test confirmation keyword detection
- Test profile update with various fields

### 6.2 Integration Tests (Manual Testing Required)
- Complete booking flow with relative dates
- Profile updates for each field
- Content filtering for blocked/harmful content
- Confirmation handling with various keywords

### 6.3 Test Cases

**Test Case 1: Complete Booking with "next Monday"**
```
User: "I have a sore throat"
Expected: Shows ENT doctors
User: "yes"
Expected: Asks for date
User: "next Monday"
Expected: Shows slots for correct Monday with correct day-of-week
User: "2 PM"
Expected: Shows booking summary
User: "confirm"
Expected: Books appointment successfully
```

**Test Case 2: Profile Update**
```
User: "update my name to John"
Expected: "Your first name has been updated to John"
```

**Test Case 3: Content Filtering**
```
User: "what's the weather"
Expected: OUT_OF_SCOPE_REPLY
User: "tell me about crypto"
Expected: OUT_OF_SCOPE_REPLY
User: "how to take drugs"
Expected: HARMFUL_REPLY
```

## 7. Deployment

### 7.1 Changes Required
1. Update `services/chat_graph.py`:
   - Replace GUARD_SYSTEM prompt
   - Replace AGENT_SYSTEM prompt
   - Update agent_node function

2. Update `services/chat_tools.py`:
   - Replace update_user_profile function

### 7.2 Rollback Plan
- Keep backup of original chat_graph.py and chat_tools.py
- If issues occur, revert to previous versions
- No database changes required

### 7.3 Monitoring
- Monitor chat logs for booking success rate
- Track profile update success/failure rate
- Monitor guard node BLOCKED/HARMFUL rates
- Track user satisfaction with date handling

## 8. Performance Considerations

### 8.1 Prompt Length
- New AGENT_SYSTEM is longer (~2500 tokens vs ~800 tokens)
- Impact: Slightly higher API costs per message
- Benefit: Significantly better accuracy and user experience

### 8.2 Date Calculations
- Minimal performance impact (simple datetime operations)
- Calculations done once per message in agent_node

### 8.3 Tool Execution
- No changes to tool execution performance
- Profile update tool has better error handling (may be slightly slower due to logging)

## 9. Security Considerations

### 9.1 Input Validation
- All date inputs validated before tool calls
- Profile update fields validated by Pydantic schemas
- No SQL injection risk (using ORM)

### 9.2 Content Filtering
- Enhanced guard prevents inappropriate content
- HARMFUL content logged for monitoring
- No PII exposed in error messages

## 10. Future Enhancements (Out of Scope)

- Add appointment rescheduling capability
- Add appointment cancellation through chat
- Support for multiple appointment booking in one conversation
- Integration with calendar systems
- SMS/email notifications through chat
- Multi-language support
- Voice input support

## 11. Correctness Properties

### Property 1: Date Consistency
**Property**: For any relative date expression, the calculated date's day-of-week must match the date value.
**Validation**: Manual testing with various date expressions
**Example**: "next Monday" on Feb 18, 2026 (Wednesday) → "2026-02-23" which is Monday ✓

### Property 2: Booking Completeness
**Property**: direct_book_appointment is called if and only if all four required parameters (doctor_id, date, start_time, end_time) are present when user confirms.
**Validation**: Manual testing with various confirmation scenarios
**Example**: User says "yes" with all params → booking succeeds ✓

### Property 3: Profile Update Atomicity
**Property**: Profile updates either succeed completely or fail completely with clear error message.
**Validation**: Manual testing with valid and invalid field values
**Example**: Valid update → success message with updated fields ✓

### Property 4: Content Filtering Accuracy
**Property**: Healthcare-related queries are ALLOWED, non-healthcare queries are BLOCKED, harmful queries return HARMFUL.
**Validation**: Manual testing with diverse query types
**Example**: "weather" → BLOCKED, "sore throat" → ALLOWED, "illegal drugs" → HARMFUL ✓

### Property 5: Conversation Memory Persistence
**Property**: Once a doctor or slot is selected, it remains in context until booking completes or user changes selection.
**Validation**: Manual testing with multi-turn conversations
**Example**: Select doctor → ask about date → doctor_id still remembered ✓
