# System Design — MeetingMind AI

## 1. Problem Statement

Meeting notes and decisions get lost between the moment they're discussed and the moment someone acts on them. MeetingMind AI closes that gap by converting any raw meeting input — text, audio, or a photo — directly into structured, trackable, assignable data.

## 2. Data Flow

User Input (text / file / audio / camera photo / uploaded photo)
│
▼
[Optional] Local PII Redaction (regex — emails, phone numbers)
│
▼
Gemini API — single call, JSON-mode, system-prompted
│
▼
Structured JSON: action items, efficiency score, tone,
risks, decisions, open questions, detected language
│
▼
st.session_state.meetings (in-memory store for the session)
│
├──► Dashboard: KPI cards, editable table, charts, timeline
├──► Carried-over / Change-since-last-meeting detector (local, no API call)
├──► Follow-up Email Generator (on-demand second API call)
├──► "Ask This Meeting" Q&A (on-demand API call, grounded in transcript)
└──► Export: CSV / Slack text / PDF report


## 3. Why a Single Gemini Call for Extraction?

Rather than making separate API calls for action items, tone, risks, decisions, and open questions, the system prompt asks Gemini to return **all of these in one JSON-mode response**. This:
- Reduces API cost and latency (one request instead of five)
- Keeps the fields internally consistent, since the model reasons about the whole meeting at once rather than in isolated fragments
- Matches the `st.form` pattern in the UI — the user submits once, gets a complete result once

Secondary features (follow-up email, Q&A chat) are deliberately kept as **separate, on-demand calls**, only triggered when the user explicitly clicks a button — this avoids unnecessary API usage for features not every user will need.

## 4. Prompt Engineering Strategy

- **System instruction, not inline prompt**: the extraction rules live in `system_instruction`, keeping the user-facing prompt (the transcript itself) clean and separate from behavior rules.
- **f-string dynamic context**: meeting date and meeting type are injected into the system prompt at runtime, so relative deadlines ("by Friday") can be resolved against the actual meeting date.
- **JSON-mode with an explicit schema**: `response_mime_type="application/json"` combined with a schema written directly into the prompt ensures the output is always parseable, removing the need for fragile regex/string parsing of free-text responses.
- **Confidence scoring**: the model is explicitly asked to self-report "High"/"Low" confidence per action item, rather than presenting every extracted item with false certainty. Items with guessed owners/deadlines are flagged for human review instead of being silently wrong.
- **Multimodal reuse of one prompt template**: the same `_system_prompt()` method is reused for text, audio, and image inputs (camera photo or uploaded photo) — only the *contents* passed to the model change, not the extraction logic or schema. This keeps all input modes consistent.

## 5. Local vs API-Based Logic

To keep the app fast and API-efficient, several features are deliberately implemented **without** calling Gemini:
- **Carried-over task detection** — uses Python's `difflib.SequenceMatcher` to compare task text similarity across meetings
- **What Changed Since Last Meeting** — computed by diffing the current and previous meeting's action item lists locally
- **PII redaction** — regex-based, runs before the transcript ever leaves the browser session, not an AI call

This separation keeps the "smart" reasoning (understanding language, inferring intent) inside Gemini calls, while pure data operations (comparing strings, computing deltas) stay local and instant.

## 6. Known Limitations

- Session state is in-memory only — meeting history is lost on app restart, since this is a single-session demo without a persistent database.
- Carried-over detection uses text similarity, so it can occasionally miss semantically similar but very differently worded tasks.
- PII redaction currently only covers text/file input, not audio or camera input.

## 7. Future Improvements

- Persistent storage (e.g. SQLite or a cloud database) so meeting history survives across sessions/users
- Dependency/impact graph between action items across a project
- Slack/Calendar integration for direct task assignment
Neeche "Commit new file" button dabao

Ho jaye toh confirm kar dena — README mein [DESIGN.md](./DESIGN.md) wala link automatically kaam karne lag jayega uske baad.
