import os
import io
import re
import html
import difflib
from datetime import datetime, date

import pandas as pd
import streamlit as st
from dateutil import parser as date_parser
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from gemini_engine import MeetingExtractorEngine

# ---------- PAGE CONFIG ----------
st.set_page_config(
    page_title="MeetingMind AI — Action Item Extractor",
    page_icon="🗂️",
    layout="wide",
)

# ---------- SESSION STATE INIT ----------
if "meetings" not in st.session_state:
    st.session_state.meetings = []
if "current_index" not in st.session_state:
    st.session_state.current_index = None
if "api_key" not in st.session_state:
    st.session_state.api_key = os.getenv("GEMINI_API_KEY", "")
if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = True
if "redact_pii" not in st.session_state:
    st.session_state.redact_pii = False


# ---------- HELPER FUNCTIONS ----------
def get_api_key():
    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        return st.session_state.api_key


def get_chart_color():
    return "#818cf8" if st.session_state.dark_mode else "#4f46e5"


def redact_pii(text: str) -> str:
    """Local, regex-based PII redaction — runs before the transcript is sent to
    the API or stored, so no extra API call and no data leaves the browser
    unredacted when enabled."""
    text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', "[REDACTED_EMAIL]", text)
    text = re.sub(r'(\+?\d{1,3}[-.\s]?)?\(?\d{3,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b',
                   "[REDACTED_PHONE]", text)
    text = re.sub(r'\b(?:\d[ -]*?){13,16}\b', "[REDACTED_NUMBER]", text)
    return text


def compute_overdue(action_items):
    today = date.today()
    overdue = 0
    for item in action_items:
        d = item.get("deadline", "")
        if d and d != "Not specified":
            try:
                if date_parser.parse(d).date() < today:
                    overdue += 1
            except Exception:
                pass
    return overdue


def find_carried_over(current_items, current_idx, all_meetings, threshold=0.6):
    """Pure string-matching (no API call) — flags tasks that look like repeats
    of pending items from earlier meetings."""
    carried = set()
    past_pending_tasks = []
    for i, m in enumerate(all_meetings):
        if i >= current_idx:
            continue
        for it in m["action_items"]:
            if it.get("status", "Pending") != "Done":
                past_pending_tasks.append(it.get("task", ""))

    for idx, item in enumerate(current_items):
        task_text = item.get("task", "")
        for past_task in past_pending_tasks:
            ratio = difflib.SequenceMatcher(None, task_text.lower(), past_task.lower()).ratio()
            if ratio >= threshold:
                carried.add(idx)
                break
    return carried


def compute_changes_since_last(current_idx, all_meetings, threshold=0.6):
    """Compares the current meeting's items against the immediately previous
    meeting's items — pure local logic, no API call."""
    if current_idx == 0:
        return None
    prev_items = all_meetings[current_idx - 1]["action_items"]
    curr_items = all_meetings[current_idx]["action_items"]

    completed = [it["task"] for it in prev_items if it.get("status") == "Done"]
    still_pending = [it["task"] for it in prev_items if it.get("status") != "Done"]

    new_items = []
    for it in curr_items:
        task_text = it.get("task", "")
        is_new = True
        for past in prev_items:
            ratio = difflib.SequenceMatcher(None, task_text.lower(), past.get("task", "").lower()).ratio()
            if ratio >= threshold:
                is_new = False
                break
        if is_new:
            new_items.append(task_text)

    return {"completed": completed, "still_pending": still_pending, "new_items": new_items}


def apply_theme():
    if st.session_state.dark_mode:
        css = """
        <style>
        .stApp {
            background-color: #0f172a;
        }
        .stApp, .stApp p, .stApp span, .stApp label, .stApp div,
        section[data-testid="stSidebar"], section[data-testid="stSidebar"] * {
            color: #e2e8f0 !important;
        }
        header[data-testid="stHeader"] {
            background-color: #0f172a !important;
        }
        section[data-testid="stSidebar"] {
            background-color: #131c31;
            border-right: 1px solid #1e293b;
        }
        h1, h2, h3, h4 {
            color: #f1f5f9 !important;
        }
        [data-testid="stMetric"] {
            background-color: #1e293b;
            border: 1px solid #334155;
            border-radius: 10px;
            padding: 14px 10px;
        }
        [data-testid="stMetricValue"] {
            color: #818cf8 !important;
        }
        .stButton>button, .stDownloadButton>button, .stFormSubmitButton>button {
            background-color: #6366f1 !important;
            color: white !important;
            border: none;
            border-radius: 8px;
            font-weight: 500;
        }
        .stButton>button:hover, .stDownloadButton>button:hover, .stFormSubmitButton>button:hover {
            background-color: #4f46e5 !important;
            color: white !important;
        }
        [data-testid="stExpander"] {
            background-color: #1a2438;
            border: 1px solid #2c3b57;
            border-radius: 10px;
        }
        [data-testid="stExpander"] summary {
            background-color: #1a2438 !important;
            color: #e2e8f0 !important;
        }
        button[kind="icon"], button[data-testid^="baseButton"] {
            background-color: transparent !important;
            color: #e2e8f0 !important;
            border: none !important;
        }
        .stTabs [data-baseweb="tab"] {
            color: #94a3b8 !important;
        }
        .stTabs [aria-selected="true"] {
            color: #818cf8 !important;
        }
        [data-testid="stDataFrame"] {
            border: 1px solid #334155;
            border-radius: 8px;
        }
        input, textarea, select {
            color: #e2e8f0 !important;
            background-color: #1e293b !important;
        }
        [data-testid="stAudioInput"] {
            background-color: #1e293b !important;
            border: 1px solid #334155 !important;
            border-radius: 8px !important;
        }
        [data-testid="stAudioInput"] * {
            background-color: transparent !important;
            color: #e2e8f0 !important;
        }
        [data-testid="stFileUploader"] {
            background-color: #1e293b !important;
            border: 1px solid #334155 !important;
            border-radius: 8px !important;
        }
        [data-testid="stFileUploader"] section {
            background-color: #1e293b !important;
        }
        [data-testid="stFileUploaderDropzone"] {
            background-color: #1e293b !important;
        }
        [data-testid="stFileUploader"] * {
            color: #e2e8f0 !important;
        }
        [data-testid="stFileUploader"] button {
            background-color: #6366f1 !important;
            color: white !important;
            border: none !important;
        }
        [data-testid="stCameraInput"] {
            background-color: #1e293b !important;
            border: 1px solid #334155 !important;
            border-radius: 8px !important;
        }
        [data-testid="stCameraInput"] > div {
            background-color: #1e293b !important;
        }
        [data-testid="stCameraInput"] * {
            color: #e2e8f0 !important;
        }
        [data-testid="stCameraInput"] button {
            background-color: #6366f1 !important;
            color: white !important;
        }
        </style>"""
    else:
        css = """
        <style>
        * {
            color: #000000 !important;
        }
        .stApp, section[data-testid="stSidebar"], header[data-testid="stHeader"],
        [data-testid="stMetric"], [data-testid="stExpander"], [data-testid="stExpander"] summary,
        [data-testid="stDataFrame"], [data-testid="stAudioInput"], [data-testid="stFileUploader"],
        [data-testid="stFileUploader"] section, [data-testid="stFileUploaderDropzone"],
        [data-testid="stCameraInput"], [data-testid="stCameraInput"] > div,
        input, textarea, select, button[kind="icon"], button[data-testid^="baseButton"],
        [data-testid="stBaseButton-secondary"], button[kind="secondary"] {
            background-color: #ffffff !important;
            border-color: #e2e8f0 !important;
        }
        svg {
            fill: #000000 !important;
        }
        .stButton>button, .stDownloadButton>button, .stFormSubmitButton>button {
            background-color: #4f46e5 !important;
            color: #ffffff !important;
            border: none !important;
            border-radius: 8px;
            font-weight: 500;
        }
        .stButton>button *, .stDownloadButton>button *, .stFormSubmitButton>button * {
            color: #ffffff !important;
        }
        .stButton>button:hover, .stDownloadButton>button:hover, .stFormSubmitButton>button:hover {
            background-color: #4338ca !important;
        }
        [data-testid="stFileUploader"] button {
            background-color: #4f46e5 !important;
        }
        [data-testid="stFileUploader"] button * {
            color: #ffffff !important;
        }
        [data-testid="stCameraInput"] button {
            background-color: #4f46e5 !important;
        }
        [data-testid="stCameraInput"] button * {
            color: #ffffff !important;
        }
        .stTabs [aria-selected="true"] {
            color: #4f46e5 !important;
        }
        </style>"""
    st.markdown(css, unsafe_allow_html=True)


def read_aloud_button(text: str, key: str):
    safe_text = html.escape(text).replace("\n", " ").replace("'", "&#39;")
    st.components.v1.html(f"""
        <button onclick="
            const u = new SpeechSynthesisUtterance(document.getElementById('{key}').innerText);
            window.speechSynthesis.cancel();
            window.speechSynthesis.speak(u);
        " style="padding:8px 14px;border-radius:6px;border:1px solid #6366f1;
                  background:#1e293b;color:#e2e8f0;cursor:pointer;">
            🔊 Read Summary Aloud
        </button>
        <p id="{key}" style="display:none;">{safe_text}</p>
    """, height=50)


def generate_pdf_report(meeting: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleStyle", parent=styles["Title"], textColor=colors.HexColor("#1f2937"))
    story = []

    story.append(Paragraph("MeetingMind AI — Report", title_style))
    story.append(Paragraph(f"<b>{meeting['title']}</b>", styles["Heading2"]))
    story.append(Paragraph(f"{meeting['type']} · {meeting['date']}", styles["Normal"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Summary", styles["Heading3"]))
    story.append(Paragraph(meeting["summary"], styles["Normal"]))
    story.append(Spacer(1, 8))

    eff = meeting.get("efficiency_score", {})
    if eff:
        story.append(Paragraph(f"Efficiency Score: {eff.get('score','-')}% — Tone: {meeting.get('meeting_tone','-')}",
                                styles["Heading4"]))
        story.append(Paragraph(eff.get("reasoning", ""), styles["Normal"]))
        story.append(Spacer(1, 8))

    decisions = meeting.get("decisions", [])
    if decisions:
        story.append(Paragraph("Decisions Made", styles["Heading3"]))
        for d in decisions:
            story.append(Paragraph(f"• {d}", styles["Normal"]))
        story.append(Spacer(1, 8))

    questions = meeting.get("open_questions", [])
    if questions:
        story.append(Paragraph("Open Questions", styles["Heading3"]))
        for q in questions:
            story.append(Paragraph(f"• {q}", styles["Normal"]))
        story.append(Spacer(1, 8))

    risks = meeting.get("risks_blockers", [])
    if risks:
        story.append(Paragraph("Risks & Blockers", styles["Heading3"]))
        for r in risks:
            story.append(Paragraph(f"• {r}", styles["Normal"]))
        story.append(Spacer(1, 8))

    story.append(Paragraph("Action Items", styles["Heading3"]))
    table_data = [["Task", "Owner", "Deadline", "Priority", "Status"]]
    for it in meeting["action_items"]:
        table_data.append([
            it.get("task", ""), it.get("owner", ""), it.get("deadline", ""),
            it.get("priority", ""), it.get("status", ""),
        ])
    table = Table(table_data, repeatRows=1, colWidths=[160, 80, 70, 60, 60])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(table)
    story.append(Spacer(1, 16))
    story.append(Paragraph(f"Generated by MeetingMind AI · {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                            styles["Italic"]))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


# ---------- APPLY THEME ----------
apply_theme()

# ---------- SIDEBAR ----------
with st.sidebar:
    st.title("🗂️ MeetingMind AI")
    st.caption("AI-powered meeting → action item pipeline")

    with st.expander("⚙️ Settings", expanded=not bool(get_api_key())):
        key_input = st.text_input("Gemini API Key", type="password",
                                   value=st.session_state.api_key,
                                   help="Get one free at aistudio.google.com/apikey")
        if key_input:
            st.session_state.api_key = key_input
        model_choice = st.selectbox("Model", ["gemini-3.6-flash", "gemini-3.5-flash-lite"], index=0)
        st.session_state.dark_mode = st.toggle("🌙 Dark mode", value=st.session_state.dark_mode)
        st.session_state.redact_pii = st.toggle("🔐 Redact PII before processing", value=st.session_state.redact_pii)
        if st.session_state.redact_pii:
            st.caption("Emails, phone numbers, and long numeric IDs will be masked locally "
                       "before the transcript is sent to Gemini or stored. (Text/file input only.)")

    st.divider()
    st.subheader("🕒 Meeting History")
    if not st.session_state.meetings:
        st.caption("No meetings processed yet.")
    else:
        for i, m in enumerate(reversed(st.session_state.meetings)):
            real_idx = len(st.session_state.meetings) - 1 - i
            if st.button(f"{m['title']} · {m['date']}", key=f"hist_{real_idx}", use_container_width=True):
                st.session_state.current_index = real_idx

apply_theme()

# ---------- HEADER ----------
st.title("🗂️ MeetingMind AI")
st.caption("Turn chaotic meeting transcripts into structured, assignable action items — powered by Gemini.")

tab_new, tab_dash, tab_trends, tab_arch = st.tabs(
    ["📝 New Meeting", "📊 Dashboard", "📈 Trends & Search", "🏗️ Architecture"])

# ---------- TAB 1: NEW MEETING ----------
with tab_new:
    st.subheader("Process a new meeting")

    input_mode = st.radio(
        "Input method",
        ["✍️ Paste transcript", "📄 Upload .txt", "🎙️ Record audio", "📸 Snap Whiteboard/Notes"],
        horizontal=True)

    with st.form("meeting_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            meeting_title = st.text_input("Meeting title", placeholder="Q3 Sprint Planning")
        with col2:
            meeting_type = st.selectbox(
                "Meeting type",
                ["Auto-detect", "Standup", "Sprint Planning", "Client Call", "1:1", "General"])
        meeting_date = st.date_input("Meeting date", value=date.today())

        transcript_text, audio_bytes, audio_mime, image_bytes, image_mime = None, None, None, None, None

        if input_mode == "✍️ Paste transcript":
            transcript_text = st.text_area("Paste raw transcript here (any language supported)", height=220,
                                            placeholder="John: We need to fix the login bug by Friday...")
        elif input_mode == "📄 Upload .txt":
            uploaded = st.file_uploader("Upload transcript (.txt)", type=["txt"])
            if uploaded:
                transcript_text = uploaded.read().decode("utf-8", errors="ignore")
        elif input_mode == "🎙️ Record audio":
            audio_file = st.audio_input("Record the meeting / summary")
            if audio_file:
                audio_bytes = audio_file.read()
                audio_mime = audio_file.type or "audio/wav"
        else:
            camera_photo = st.camera_input("Take a photo of the whiteboard or notes")
            if camera_photo:
                image_bytes = camera_photo.read()
                image_mime = camera_photo.type or "image/jpeg"

        submitted = st.form_submit_button("🚀 Extract Action Items", use_container_width=True)

    if submitted:
        api_key = get_api_key()
        if not api_key:
            st.error("Please enter your Gemini API key in the sidebar first.")
        elif not transcript_text and not audio_bytes and not image_bytes:
            st.error("Please paste a transcript, upload a file, record audio, or take a photo.")
        else:
            with st.spinner("Gemini is reading the input and extracting action items, risks, and more..."):
                try:
                    engine = MeetingExtractorEngine(api_key=api_key, model_name=model_choice)
                    if audio_bytes:
                        result = engine.extract_from_audio(
                            audio_bytes, mime_type=audio_mime, meeting_type=meeting_type,
                            meeting_date=str(meeting_date))
                    elif image_bytes:
                        result = engine.extract_from_image(
                            image_bytes, mime_type=image_mime, meeting_type=meeting_type,
                            meeting_date=str(meeting_date))
                    else:
                        clean_transcript = transcript_text
                        if st.session_state.redact_pii:
                            clean_transcript = redact_pii(transcript_text)
                        result = engine.extract_from_text(
                            clean_transcript, meeting_type=meeting_type,
                            meeting_date=str(meeting_date))

                    items = result.get("action_items", [])
                    for it in items:
                        it["status"] = "Pending"

                    meeting_record = {
                        "title": meeting_title or f"{result.get('meeting_type_detected', meeting_type)} — {meeting_date}",
                        "date": str(meeting_date),
                        "type": result.get("meeting_type_detected", meeting_type),
                        "detected_language": result.get("detected_language", "English"),
                        "summary": result.get("summary", ""),
                        "transcript": result.get("transcript", transcript_text or ""),
                        "meeting_tone": result.get("meeting_tone", "Neutral"),
                        "efficiency_score": result.get("efficiency_score", {}),
                        "risks_blockers": result.get("risks_blockers", []),
                        "decisions": result.get("decisions", []),
                        "open_questions": result.get("open_questions", []),
                        "action_items": items,
                        "qa_history": [],
                        "created_at": datetime.now().isoformat(),
                    }
                    st.session_state.meetings.append(meeting_record)
                    idx = len(st.session_state.meetings) - 1

                    carried = find_carried_over(items, idx, st.session_state.meetings)
                    meeting_record["carried_over_indices"] = list(carried)

                    st.session_state.current_index = idx
                    st.success("✅ Done! Check the Dashboard tab.")
                except Exception as e:
                    st.error(f"Something went wrong: {e}")

# ---------- TAB 2: DASHBOARD ----------
with tab_dash:
    if st.session_state.current_index is None or not st.session_state.meetings:
        st.info("No meeting processed yet. Start from the 'New Meeting' tab.")
    else:
        idx = st.session_state.current_index
        meeting = st.session_state.meetings[idx]
        items = meeting["action_items"]

        st.subheader(meeting["title"])
        tone_emoji = {"Positive": "🟢", "Neutral": "🟡", "Tense": "🔴"}.get(meeting.get("meeting_tone", "Neutral"), "🟡")
        lang = meeting.get("detected_language", "English")
        lang_note = f" · 🌐 Detected: {lang}" if lang and lang != "English" else ""
        st.caption(f"{meeting['type']} · {meeting['date']} · {tone_emoji} Tone: {meeting.get('meeting_tone','Neutral')}{lang_note}")

        with st.expander("📋 Meeting Summary", expanded=True):
            st.write(meeting["summary"])
            read_aloud_button(meeting["summary"], key=f"tts_{idx}")

        eff = meeting.get("efficiency_score", {})
        if eff:
            st.markdown(f"**⏱️ Meeting Efficiency: {eff.get('score', '—')}%**")
            st.caption(eff.get("reasoning", ""))

        changes = compute_changes_since_last(idx, st.session_state.meetings)
        if changes:
            with st.expander("🔄 What Changed Since Last Meeting", expanded=True):
                cc1, cc2, cc3 = st.columns(3)
                with cc1:
                    st.markdown(f"**✅ Completed ({len(changes['completed'])})**")
                    for t in changes["completed"]:
                        st.caption(f"• {t}")
                with cc2:
                    st.markdown(f"**⏳ Still Pending ({len(changes['still_pending'])})**")
                    for t in changes["still_pending"]:
                        st.caption(f"• {t}")
                with cc3:
                    st.markdown(f"**🆕 New This Time ({len(changes['new_items'])})**")
                    for t in changes["new_items"]:
                        st.caption(f"• {t}")

        decisions = meeting.get("decisions", [])
        if decisions:
            with st.expander(f"🎯 Decisions Made ({len(decisions)})", expanded=True):
                for d in decisions:
                    st.success(d)

        questions = meeting.get("open_questions", [])
        if questions:
            with st.expander(f"❓ Open Questions ({len(questions)})", expanded=True):
                for q in questions:
                    st.info(q)

        risks = meeting.get("risks_blockers", [])
        if risks:
            with st.expander(f"⚠️ Risks & Blockers ({len(risks)})", expanded=True):
                for r in risks:
                    st.warning(r)

        carried = set(meeting.get("carried_over_indices", []))
        if carried:
            st.info(f"⏳ {len(carried)} task(s) look carried over from a previous meeting (pending repeat detected).")

        total = len(items)
        high_priority = sum(1 for i in items if i.get("priority") == "High")
        unassigned = sum(1 for i in items if i.get("owner", "Unassigned") == "Unassigned")
        overdue = compute_overdue(items)
        done = sum(1 for i in items if i.get("status") == "Done")

        prev_total = len(st.session_state.meetings[idx - 1]["action_items"]) if idx > 0 else None

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Action Items", total, delta=(total - prev_total) if prev_total is not None else None)
        c2.metric("High Priority", high_priority)
        c3.metric("Unassigned", unassigned)
        c4.metric("Overdue", overdue)

        if total:
            st.progress(done / total, text=f"{done}/{total} tasks completed ({done/total*100:.0f}%)")

        st.divider()
        st.markdown("#### ✏️ Action Items (editable)")
        df = pd.DataFrame(items)
        if not df.empty:
            edited_df = st.data_editor(
                df,
                column_config={
                    "priority": st.column_config.SelectboxColumn("priority", options=["High", "Medium", "Low"]),
                    "status": st.column_config.SelectboxColumn("status", options=["Pending", "Done"]),
                    "confidence": st.column_config.TextColumn("confidence", disabled=True),
                },
                num_rows="dynamic",
                use_container_width=True,
            )
            st.session_state.meetings[idx]["action_items"] = edited_df.to_dict("records")

            colA, colB, colC = st.columns(3)
            with colA:
                st.markdown("##### 👥 Owner workload")
                if "owner" in edited_df.columns:
                    st.bar_chart(edited_df["owner"].value_counts(), color=get_chart_color())
            with colB:
                st.markdown("##### 🎯 Priority breakdown")
                st.bar_chart(edited_df["priority"].value_counts(), color=get_chart_color())
            with colC:
                st.markdown("##### 📤 Export")
                csv = edited_df.to_csv(index=False).encode("utf-8")
                st.download_button("⬇️ CSV", csv, file_name=f"{meeting['title']}_action_items.csv",
                                    mime="text/csv", use_container_width=True)

                slack_text = f"*{meeting['title']}* ({meeting['date']})\n\n{meeting['summary']}\n\n"
                for it in edited_df.to_dict("records"):
                    slack_text += f"• [{it.get('priority','-')}] {it.get('task','')} — _{it.get('owner','Unassigned')}_ (due {it.get('deadline','TBD')})\n"
                st.download_button("⬇️ Slack-format .txt", slack_text.encode("utf-8"),
                                    file_name=f"{meeting['title']}_slack.txt", use_container_width=True)

                pdf_bytes = generate_pdf_report(meeting)
                st.download_button("⬇️ PDF Report", pdf_bytes, file_name=f"{meeting['title']}_report.pdf",
                                    mime="application/pdf", use_container_width=True)

            st.markdown("##### 🗓️ Timeline (sorted by deadline)")
            def sort_key(it):
                try:
                    return date_parser.parse(it.get("deadline", "")).date()
                except Exception:
                    return date.max
            for it in sorted(edited_df.to_dict("records"), key=sort_key):
                with st.expander(f"{it.get('deadline','Not specified')} — {it.get('task','')}"):
                    st.write(f"**Owner:** {it.get('owner','Unassigned')} · **Priority:** {it.get('priority','-')} "
                             f"· **Confidence:** {it.get('confidence','-')}")

            st.divider()
            if st.button("✉️ Draft Follow-up Email"):
                api_key = get_api_key()
                if not api_key:
                    st.error("Please enter your API key in the sidebar first.")
                else:
                    with st.spinner("Drafting the email..."):
                        engine = MeetingExtractorEngine(api_key=api_key, model_name=model_choice)
                        email_text = engine.generate_followup_email(meeting)
                        st.text_area("Copy-paste ready email", email_text, height=250)
                        st.download_button("⬇️ Download email .txt", email_text.encode("utf-8"),
                                            file_name=f"{meeting['title']}_followup.txt")

            st.divider()
            st.markdown("#### 💬 Ask This Meeting")
            for turn in meeting.get("qa_history", []):
                st.chat_message("user").write(turn["question"])
                st.chat_message("assistant").write(turn["answer"])

            question = st.chat_input("Ask something about this meeting, e.g. 'What did John commit to?'")
            if question:
                api_key = get_api_key()
                if not api_key:
                    st.error("Please enter your API key in the sidebar first.")
                else:
                    with st.spinner("Thinking..."):
                        engine = MeetingExtractorEngine(api_key=api_key, model_name=model_choice)
                        answer = engine.ask_question(meeting, question, meeting.get("qa_history", []))
                        meeting.setdefault("qa_history", []).append({"question": question, "answer": answer})
                        st.rerun()
        else:
            st.warning("No action items were found for this meeting.")

# ---------- TAB 3: TRENDS & SEARCH ----------
with tab_trends:
    if not st.session_state.meetings:
        st.info("Process at least one meeting to see trends and search here.")
    else:
        all_items_flat = []
        for m in st.session_state.meetings:
            for it in m["action_items"]:
                row = dict(it)
                row["meeting"] = m["title"]
                row["meeting_date"] = m["date"]
                all_items_flat.append(row)

        total_all = len(all_items_flat)
        done_all = sum(1 for i in all_items_flat if i.get("status") == "Done")

        c1, c2, c3 = st.columns(3)
        c1.metric("Total Meetings", len(st.session_state.meetings))
        c2.metric("Total Tasks Assigned", total_all)
        c3.metric("Overall Completion", f"{(done_all/total_all*100) if total_all else 0:.0f}%")

        trend_df = pd.DataFrame([
            {"meeting": m["title"], "tasks": len(m["action_items"])}
            for m in st.session_state.meetings
        ])
        st.markdown("##### Tasks per meeting")
        st.bar_chart(trend_df.set_index("meeting"), color=get_chart_color())

        eff_df = pd.DataFrame([
            {"meeting": m["title"], "efficiency": m.get("efficiency_score", {}).get("score", 0)}
            for m in st.session_state.meetings
        ])
        st.markdown("##### Meeting efficiency trend")
        st.line_chart(eff_df.set_index("meeting"), color=get_chart_color())

        owner_counts = pd.Series([it.get("owner", "Unassigned") for it in all_items_flat]).value_counts()
        st.markdown("##### Workload across ALL meetings")
        st.bar_chart(owner_counts, color=get_chart_color())

        st.divider()
        st.markdown("##### 🔍 Global task search")
        search_query = st.text_input("Search by owner, task keyword, or category")
        if search_query:
            search_df = pd.DataFrame(all_items_flat)
            mask = search_df.apply(
                lambda row: search_query.lower() in str(row.get("owner", "")).lower()
                or search_query.lower() in str(row.get("task", "")).lower()
                or search_query.lower() in str(row.get("category", "")).lower(),
                axis=1,
            )
            results = search_df[mask]
            if results.empty:
                st.caption("No matching tasks found.")
            else:
                st.dataframe(
                    results[["task", "owner", "deadline", "priority", "status", "meeting", "meeting_date"]],
                    use_container_width=True,
                )

# ---------- TAB 4: ARCHITECTURE ----------
with tab_arch:
    st.subheader("System Architecture")
    st.markdown("""
**Data flow:** Input (text / file / audio / camera photo) → optional local PII redaction
(regex, no API call) → Gemini (system-prompted, JSON-mode, single call returns action items
+ efficiency score + tone + risks + decisions + open questions + confidence + detected
language) → `st.session_state` → editable dashboard → carried-over and change-since-last-meeting
detection (local string-matching, no extra API call) → export (CSV / Slack / PDF) / follow-up
email / Q&A chat (each an on-demand second API call, only triggered by explicit user action
to keep API usage efficient).
""")
    st.components.v1.html("""
        <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
        <div class="mermaid">
        flowchart TD
            A[User Input] --> B[Gemini API JSON Mode]
            B --> C[Structured Data]
            C --> D[Session State]
            D --> E[Dashboard KPIs and Charts]
            D --> F[Carried Over Detector]
            D --> G[Change Since Last Meeting]
            E --> H[Export CSV PDF Slack]
            E --> I[Ask This Meeting Chat]
            E --> J[Follow Up Email]
        </div>
        <script>mermaid.initialize({startOnLoad:true, theme:'dark'});</script>
    """, height=380)