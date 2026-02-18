# Chatbot Robustness Improvements - Requirements

## 1. Overview

The medical appointment chatbot currently has several critical issues that prevent it from functioning reliably in production. This spec addresses conversation flow problems, date handling errors, confirmation handling, profile update failures, and inappropriate content filtering.

## 2. Problem Statement

### Current Issues:
1. **Confirmation handling broken**: When users say "yes", "confirm", "go for it", etc., the bot doesn't book appointments
2. **Date parsing failures**: "next Monday" and relative dates are incorrectly calculated or not working
3. **Day-of-week mismatch**: Shows "Monday, 24th February 2026" when 24th is actually Tuesday
4. **Profile update errors**: Profile updates fail with generic error messages
5. **Missing conversation context**: Bot doesn't remember doctor selection or slot selection during booking flow
6. **Inappropriate content handling**: Bot is not responding anything  responds to crypto, weather, drugs, illegal activities instead of blocking and predefined reply for harmful reply
7. **Doctor list format issue in message**: Bot doesn't properly formating doctor names. e.g.1. [Dr. dr.mhm yo](7723f721-c188-47a8-8e8b-30d48864dcc7): 13 years of experience, consultation fee: $1000.00
2. [Dr. Sarah Kapur](f643240a-b976-40df-879a-3f0b66128a9b): 7 years of experience, also specializes in geriatrics

## 3. User Stories

### 3.1 Appointment Booking Flow
**As a** patient  
**I want to** book an appointment with natural conversation  
**So that** I can easily schedule doctor visits without confusion

**Acceptance Criteria:**
- User can describe symptoms and get doctor recommendations
- User can select a doctor by saying "yes" or "the first one" or doctor name
- Bot remembers which doctor was selected throughout the conversation
- User can say "next Monday" or "tomorrow" and bot calculates correct date
- Bot shows correct day-of-week for any date
- User can select a time slot and bot remembers it
- When user says "yes", "confirm", "book it", "go for it", bot books if all info is present
- If info is missing when user confirms, bot asks specifically for missing details

### 3.2 Confirmation Handling
**As a** patient  
**I want** my confirmations to be understood  
**So that** appointments are booked when I agree

**Acceptance Criteria:**
- Bot recognizes: "yes", "sure", "ok", "confirm", "book it", "go for it", "let's do it", "proceed"
- Bot checks if doctor_id, date, start_time, end_time are all present
- If all present, bot calls direct_book_appointment
- If any missing, bot asks for the specific missing information
- Bot never says "I'll book it" without actually calling the booking tool

### 3.3 Date Handling
**As a** patient  
**I want** to use natural date expressions  
**So that** I don't have to calculate dates myself

**Acceptance Criteria:**
- "tomorrow" → calculates next day correctly
- "next Monday" → finds the coming Monday (not today if today is Monday)
- "next Tuesday" → finds the coming Tuesday
- "Monday" → assumes next occurrence of Monday
- All dates converted to YYYY-MM-DD format before tool calls
- Day-of-week displayed matches the actual date (e.g., "Tuesday, February 24th 2026")

### 3.4 Profile Updates
**As a** patient  
**I want** to update my profile through chat  
**So that** my information stays current

**Acceptance Criteria:**
- User can say "update my name to John" and it works
- User can say "change my phone number to 1234567890" and it works
- Bot extracts field name and new value correctly
- Bot calls update_user_profile with only the changed field
- Bot confirms successful update with the new value
- If update fails, bot shows specific error message

### 3.5 Content Filtering
**As a** system administrator  
**I want** the bot to block inappropriate queries  
**So that** it stays focused on healthcare

**Acceptance Criteria:**
- Bot blocks: weather queries, crypto questions, illegal activities, drug abuse
- Bot allows: greetings, health symptoms, appointment booking, profile management
- Bot responds with appropriate out-of-scope message for blocked content
- Bot responds with harmful content warning for abusive/illegal requests

### 3.6 Conversation Memory
**As a** patient  
**I want** the bot to remember context  
**So that** I don't have to repeat information

**Acceptance Criteria:**
- After showing doctor list, bot remembers which doctor user selected
- After showing time slots, bot remembers which slot user picked
- Bot maintains doctor_id, doctor_name, date, start_time, end_time in conversation
- Bot can reference previous selections: "Would you like to book with Dr. Smith at 2:00 PM?"

## 4. Technical Requirements

### 4.1 Date Calculation
- Implement robust date parsing for relative dates
- Use Python's datetime to calculate "next Monday", "tomorrow", etc.
- Always validate day-of-week matches the date
- Format dates consistently: "Tuesday, February 24th 2026"

### 4.2 Confirmation Detection
- Expand confirmation keyword list in system prompt
- Add logic to check for all required booking parameters
- Implement parameter validation before calling direct_book_appointment

### 4.3 Profile Update Tool
- Fix update_user_profile tool to handle single field updates
- Ensure proper error handling and error message propagation
- Validate field names before attempting update

### 4.4 Guard System
- Update GUARD_SYSTEM prompt to block weather, crypto, illegal content
- Keep allowing health-related queries and greetings
- Improve HARMFUL detection for drug abuse and illegal activities

### 4.5 Conversation State
- Enhance AGENT_SYSTEM prompt with explicit memory instructions
- Add examples of maintaining context across turns
- Implement slot-filling pattern for booking flow

## 5. Out of Scope

- Payment processing changes
- Doctor availability algorithm changes
- Database schema modifications
- Frontend changes
- Email notification content changes

## 6. Success Metrics

- 100% of confirmation keywords trigger booking when all info present
- 100% of relative dates calculate correctly
- 100% of day-of-week labels match actual dates
- Profile updates succeed for all valid field changes
- Inappropriate content blocked with 95%+ accuracy
- Booking completion rate increases by 50%+

## 7. Dependencies

- Existing LangGraph chat system
- OpenRouter/OpenAI API
- PostgreSQL database
- Existing appointment and profile APIs

## 8. Assumptions

- Users will provide information in natural language
- Bot has access to current date/time
- Database contains valid doctor and availability data
- Users are authenticated before chatting
