# Chatbot Robustness Improvements - Tasks

## 1. Update Guard System Prompt
- [ ] 1.1 Replace GUARD_SYSTEM prompt in services/chat_graph.py with enhanced version
  - Add explicit BLOCKED examples for weather, crypto, cooking, sports, tech
  - Add explicit HARMFUL examples for illegal activities, drug abuse
  - Clarify health symptoms are ALLOWED
  - Test with: "what's the weather", "tell me about crypto", "how to take drugs"

## 2. Update Agent System Prompt
- [ ] 2.1 Replace AGENT_SYSTEM prompt in services/chat_graph.py with enhanced version
  - Add conversation memory section with explicit variable tracking
  - Add confirmation handling section with keyword list
  - Add date handling section with calculation examples
  - Add step-by-step booking workflow
  - Add profile update examples
  - Test prompt formatting with .format() placeholders

## 3. Enhance Date Injection in agent_node
- [ ] 3.1 Update agent_node function in services/chat_graph.py
  - Calculate next 7 days with day-of-week
  - Add today_full and tomorrow_full variables
  - Inject next_week_dates into system prompt
  - Test date calculations for various days of week

## 4. Fix Profile Update Tool
- [ ] 4.1 Update update_user_profile function in services/chat_tools.py
  - Add detailed success message with updated fields
  - Add detailed error messages with attempted fields
  - Add exception logging with stack trace
  - Return new_values in success response
  - Test with valid and invalid field updates

## 5. Integration Testing
- [ ] 5.1 Test complete booking flow with relative dates
  - Test "tomorrow" booking
  - Test "next Monday" booking
  - Test "next Tuesday" booking
  - Verify day-of-week matches date
  
- [ ] 5.2 Test confirmation handling
  - Test "yes" confirmation
  - Test "confirm" confirmation
  - Test "go for it" confirmation
  - Test "book it" confirmation
  - Verify booking completes when all info present
  - Verify bot asks for missing info when incomplete
  
- [ ] 5.3 Test profile updates
  - Test first_name update
  - Test phone_number update
  - Test city update
  - Verify success messages
  - Test invalid field values
  
- [ ] 5.4 Test content filtering
  - Test "what's the weather" → BLOCKED
  - Test "tell me about crypto" → BLOCKED
  - Test "how to take drugs" → HARMFUL
  - Test "how to make money illegal" → HARMFUL
  - Test "I have a sore throat" → ALLOWED
  - Test "hi" → ALLOWED
  
- [ ] 5.5 Test conversation memory
  - Select doctor, then provide date → verify doctor remembered
  - Select slot, then confirm → verify slot remembered
  - Complete full booking flow → verify all context maintained

## 6. Documentation
- [ ] 6.1 Update code comments in chat_graph.py
  - Document new date injection logic
  - Document prompt structure
  
- [ ] 6.2 Update code comments in chat_tools.py
  - Document profile update error handling
  - Document return value structure
