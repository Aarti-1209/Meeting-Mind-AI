import json
from datetime import datetime
from google import genai
from google.genai import types


class MeetingExtractorEngine:
    """
    Core AI engine: converts raw/chaotic meeting transcripts (text, audio, or
    a photo of whiteboard/notes) into structured, assignable action items
    using Gemini's native JSON-mode structured output. Also detects meeting
    efficiency, tone, risks/blockers, decisions, open questions, and drafts
    follow-up emails.
    """

    def __init__(self, api_key: str, model_name: str = "gemini-3.6-flash"):
        if not api_key:
            raise ValueError("Gemini API key is missing.")
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name

    def _system_prompt(self, meeting_type: str, meeting_date: str, need_transcript_field: bool) -> str:
        if meeting_type == "Auto-detect":
            type_note = ("You must first infer the meeting type yourself from the "
                          "content (e.g. Standup, Sprint Planning, Client Call, 1:1, General) "
                          "and put it in 'meeting_type_detected'.")
        else:
            type_note = f"The meeting type is given as '{meeting_type}'; echo it back in 'meeting_type_detected'."

        transcript_field = ('  "transcript": "the full transcription of what was said/written, as accurately as possible",\n'
                             if need_transcript_field else "")

        return f"""You are an elite Executive Assistant AI. Your job is to read a raw,
often messy meeting transcript and convert it into clean, structured,
assignable action items, PLUS assess meeting quality, tone, risks, decisions,
and open questions.

Context:
- Meeting date: {meeting_date}
- {type_note}
- The input may be written in ANY language. Detect the language it was written in
  and put it in 'detected_language' (e.g. "English", "Hindi", "Hinglish", "Spanish").
  Regardless of the input language, write ALL output fields (summary, decisions,
  open_questions, action item text, etc.) in clear, professional English.

Rules for action items:
- Extract every concrete action item, decision, or follow-up. Never invent tasks not discussed.
- Infer an owner ONLY if a name is clearly tied to the task, else "Unassigned".
- Infer a deadline ONLY if stated or clearly implied (e.g. "by Friday" -> compute the actual
  date relative to the meeting date). Otherwise use "Not specified".
- Assign priority based on urgency language used ("ASAP", "blocker", "critical" = High).
- For each item, add a "confidence" field: "High" if you're clearly certain about the
  task/owner/deadline, "Low" if you had to guess or infer loosely. Be honest — this is
  used to flag items for human review, so don't inflate confidence.

Rules for efficiency_score:
- Estimate what % of the meeting's discussion was genuinely actionable/productive vs
  rambling, tangents, or repetition. Score 0-100. Give a 1-2 sentence reasoning.

Rules for meeting_tone:
- Classify the overall tone as exactly one of: "Positive", "Neutral", "Tense".

Rules for risks_blockers:
- Scan for any blocker/risk language ("we're blocked on", "waiting on", "at risk",
  "concerned about", "issue with"). List each as a short string. Empty list if none found.

Rules for decisions:
- List concrete decisions the team explicitly made or agreed on (e.g. "Team agreed to use
  Stripe instead of Razorpay for payments"). Do not include action items here, only decisions.
  Empty list if none were made.

Rules for open_questions:
- List questions that were raised but left UNRESOLVED by the end of the meeting (e.g.
  "Unclear who owns the vendor escalation"). Empty list if everything was resolved.

Return ONLY valid JSON matching exactly this schema, nothing else:
{{
  "meeting_type_detected": "string",
  "detected_language": "string",
{transcript_field}  "summary": "2-3 sentence plain-English summary of the meeting",
  "meeting_tone": "Positive | Neutral | Tense",
  "efficiency_score": {{"score": 0, "reasoning": "string"}},
  "risks_blockers": ["string"],
  "decisions": ["string"],
  "open_questions": ["string"],
  "action_items": [
    {{
      "task": "string",
      "owner": "string",
      "deadline": "YYYY-MM-DD or 'Not specified'",
      "priority": "High | Medium | Low",
      "category": "short tag like Engineering, Marketing, Finance, Ops",
      "confidence": "High | Low"
    }}
  ]
}}"""

    def extract_from_text(self, transcript: str, meeting_type: str = "General",
                           meeting_date: str = None) -> dict:
        meeting_date = meeting_date or datetime.now().strftime("%Y-%m-%d")
        config = types.GenerateContentConfig(
            system_instruction=self._system_prompt(meeting_type, meeting_date, need_transcript_field=False),
            response_mime_type="application/json",
            temperature=0.2,
        )
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[f"Raw meeting transcript:\n\n{transcript}"],
            config=config,
        )
        result = json.loads(response.text)
        result["transcript"] = transcript
        return result

    def extract_from_audio(self, audio_bytes: bytes, mime_type: str = "audio/wav",
                            meeting_type: str = "General", meeting_date: str = None) -> dict:
        meeting_date = meeting_date or datetime.now().strftime("%Y-%m-%d")
        audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
        config = types.GenerateContentConfig(
            system_instruction=self._system_prompt(meeting_type, meeting_date, need_transcript_field=True)
            + "\n\nFirst listen to the audio carefully, then extract everything directly from what was said.",
            response_mime_type="application/json",
            temperature=0.2,
        )
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[audio_part, "Transcribe this meeting recording and extract structured data from it."],
            config=config,
        )
        return json.loads(response.text)

    def extract_from_image(self, image_bytes: bytes, mime_type: str = "image/jpeg",
                            meeting_type: str = "General", meeting_date: str = None) -> dict:
        """Reads a photo of a whiteboard, sticky notes, or handwritten meeting
        notes and extracts the same structured data as a transcript would."""
        meeting_date = meeting_date or datetime.now().strftime("%Y-%m-%d")
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        config = types.GenerateContentConfig(
            system_instruction=self._system_prompt(meeting_type, meeting_date, need_transcript_field=True)
            + "\n\nThe input is a PHOTO of a whiteboard, sticky notes, or handwritten meeting "
              "notes, not a transcript. Carefully read all visible handwriting and text, "
              "reconstruct it into the 'transcript' field as plain text, then extract "
              "structured data from what you read.",
            response_mime_type="application/json",
            temperature=0.2,
        )
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[image_part, "Read this photo of meeting notes and extract structured data from it."],
            config=config,
        )
        return json.loads(response.text)

    def generate_followup_email(self, meeting: dict) -> str:
        """Drafts a copy-paste-ready recap/follow-up email from an already-extracted meeting."""
        prompt = f"""Draft a short, professional follow-up email recapping this meeting.
Write it in professional English. Include a greeting, a 2-line summary, a clean bullet
list of action items with owner and deadline, and a polite closing. No subject line,
just the email body.

Meeting: {meeting['title']} ({meeting['date']})
Summary: {meeting['summary']}
Action items: {json.dumps(meeting['action_items'])}
"""
        config = types.GenerateContentConfig(temperature=0.4)
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[prompt],
            config=config,
        )
        return response.text.strip()

    def ask_question(self, meeting: dict, question: str, qa_history: list = None) -> str:
        """Answers a follow-up question about a specific meeting, grounded only in
        that meeting's transcript and extracted data. Keeps short chat memory."""
        qa_history = qa_history or []
        history_text = ""
        for turn in qa_history[-5:]:
            history_text += f"\nQ: {turn['question']}\nA: {turn['answer']}"

        prompt = f"""You are answering questions about ONE specific meeting. Only use the
information given below — if the answer isn't in it, say so honestly, don't guess.

Meeting title: {meeting['title']} ({meeting['date']})
Summary: {meeting['summary']}
Full transcript: {meeting.get('transcript', 'Not available')}
Action items: {json.dumps(meeting['action_items'])}
Decisions: {json.dumps(meeting.get('decisions', []))}
Open questions: {json.dumps(meeting.get('open_questions', []))}
Risks/Blockers: {json.dumps(meeting.get('risks_blockers', []))}

Previous Q&A in this conversation:{history_text if history_text else " (none yet)"}

New question: {question}

Answer concisely, in 2-4 sentences."""
        config = types.GenerateContentConfig(temperature=0.2)
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[prompt],
            config=config,
        )
        return response.text.strip()