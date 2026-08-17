"""ADHD screening battery - single-page Streamlit front end.

Sections are presented one at a time, OA style: participant details, then each
instrument in turn, then a review step, then feedback. Results are written to
the database and exported as a combined Excel workbook from the admin board.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import os
import time

import streamlit as st

from assessment import admin, db, keepalive
from assessment.instruments import ASRS, HSPS, INSTRUMENTS, PSS, RMEQ, WHO5, Instrument
from assessment.scoring import ScoreResult, score_all

st.set_page_config(
    page_title="ADHD Screening Battery",
    page_icon="🧠",
    layout="centered",
    initial_sidebar_state="collapsed",
)


# --------------------------------------------------------------------------
# Page plan - long instruments are split so no single screen is overwhelming
# --------------------------------------------------------------------------
SECRET_KEYS = ("ADMIN_KEY", "DATABASE_URL", "DB_PATH", "SELF_PING_URL",
               "SELF_PING_INTERVAL")


def _bridge_secrets() -> None:
    """Mirror Streamlit secrets into the environment.

    ``db`` and ``keepalive`` are deliberately framework-free and read
    ``os.environ``. Streamlit Cloud currently also exports secrets as
    environment variables, but relying on that would mean a mistyped or
    unexported DATABASE_URL silently falls back to SQLite - which on an
    ephemeral disk loses data. Copying them here makes the behaviour explicit
    and version-independent. Real environment variables still win.
    """
    try:
        secrets = st.secrets
    except Exception:  # no secrets.toml configured at all
        return
    for key in SECRET_KEYS:
        if os.environ.get(key):
            continue
        try:
            value = secrets.get(key)
        except Exception:
            value = None
        if value not in (None, ""):
            os.environ[key] = str(value)


@st.cache_resource
def _boot() -> dict:
    """One-time process setup: database tables and the keep-alive thread.

    A database that cannot be reached is reported rather than raised: the
    host redacts tracebacks, so an uncaught error here shows the operator a
    stack trace with no cause in it. ``_page_db_error`` renders something
    actionable instead.
    """
    _bridge_secrets()
    db_error = ""
    try:
        db.get_engine()
    except Exception as exc:
        db_error = db.sanitise_error(exc)
    return {"db_error": db_error, "keepalive": keepalive.start()}


def _page_db_error(message: str) -> None:
    """Explain an unreachable database without leaking the password."""
    st.error("The app cannot reach its database, so it is not accepting "
             "responses. Nothing has been lost.", icon="🚨")
    st.caption("Participants see this page too, so no credentials are shown.")

    target = db.describe_target()
    if target.get("configured"):
        st.markdown("**Configured target**")
        st.write(
            {
                "host": target.get("host"),
                "port": target.get("port"),
                "database": target.get("database"),
                "username": target.get("username"),
                "password set": "yes" if target.get("has_password") else "NO",
            }
        )

        if target.get("supabase_direct"):
            st.warning(
                "**This is Supabase's direct connection host, which is "
                "IPv6-only.** Streamlit Cloud has no IPv6, so it can never "
                "reach it — this is the usual cause. In Supabase go to "
                "*Project Settings → Database → Connection string* and copy "
                "the **Session pooler** URI instead. Its host looks like "
                "`aws-0-<region>.pooler.supabase.com` and the username "
                "includes your project ref.",
                icon="📡",
            )
        elif not target.get("has_password"):
            st.warning(
                "No password in the connection string. Replace the "
                "`[YOUR-PASSWORD]` placeholder with the real database "
                "password. If it contains `@`, `/`, `:` or `#`, percent-encode "
                "those characters."
            )
        else:
            st.info(
                "Common causes: the database is paused (free Supabase and Neon "
                "projects idle out — open the dashboard to wake it), a wrong "
                "password, or a host typo. If the password contains `@`, `/`, "
                "`:` or `#`, it must be percent-encoded."
            )
    else:
        st.warning(
            "`DATABASE_URL` is not set at all. Add it under *Manage app → "
            "Settings → Secrets*, then reboot."
        )

    with st.expander("Error detail (password removed)"):
        st.code(message or "no detail captured")

    st.caption(
        "After changing secrets, reboot the app from *Manage app* — secrets "
        "are read at startup."
    )


def _pages() -> list[dict]:
    pages: list[dict] = [{"kind": "intro", "title": "Welcome"}]
    pages.append({"kind": "details", "title": "About you"})

    def add(inst: Instrument, chunks: list[tuple[int, int]]) -> None:
        for index, (start, end) in enumerate(chunks, start=1):
            pages.append(
                {
                    "kind": "instrument",
                    "instrument": inst.key,
                    "start": start,
                    "end": end,
                    "part": index,
                    "parts": len(chunks),
                    "title": inst.short_name,
                }
            )

    add(ASRS, [(1, 6), (7, 18)])
    add(PSS, [(1, 10)])
    add(WHO5, [(1, 5)])
    add(RMEQ, [(1, 5)])
    add(HSPS, [(1, 9), (10, 18), (19, 27)])

    pages.append({"kind": "review", "title": "Review"})
    pages.append({"kind": "results", "title": "Your feedback"})
    return pages


PAGES = _pages()
TOTAL_STEPS = len(PAGES)


def _init_state() -> None:
    st.session_state.setdefault("page_index", 0)
    st.session_state.setdefault("responses", {})
    st.session_state.setdefault("participant", {})
    st.session_state.setdefault("started_at", time.time())
    st.session_state.setdefault("submission_id", None)
    st.session_state.setdefault("results", None)


def _goto(index: int) -> None:
    st.session_state.page_index = max(0, min(index, TOTAL_STEPS - 1))
    st.rerun()


# --------------------------------------------------------------------------
# Rendering helpers
# --------------------------------------------------------------------------
def _progress() -> None:
    index = st.session_state.page_index
    st.progress((index) / (TOTAL_STEPS - 1), text=f"Step {index + 1} of {TOTAL_STEPS}")


def _page_items(inst: Instrument, start: int, end: int) -> list:
    return [item for item in inst.items if start <= item.number <= end]


def _render_items(items: list) -> None:
    """Render the radio for each item.

    These live inside an ``st.form``, so changing one does not rerun the
    script - the whole page is submitted in a single round trip. On a
    65-question battery that is 8 reruns per participant instead of 65,
    which is what makes a whole class sitting the test at once comfortable.
    """
    responses = st.session_state.responses

    for item in items:
        widget_key = f"widget_{item.id}"
        index = None
        if widget_key not in st.session_state:
            current = responses.get(item.id)
            if current is not None:
                values = [value for _, value in item.options]
                if current in values:
                    index = values.index(current)

        st.markdown(f"**{item.number}. {item.text}**")
        st.radio(
            label=f"Response for item {item.number}",
            options=item.labels,
            index=index,
            key=widget_key,
            horizontal=(
                len(item.labels) <= 7 and max(len(l) for l in item.labels) <= 24
            ),
            label_visibility="collapsed",
        )
        st.write("")


def _harvest_items(items: list) -> list[str]:
    """Copy submitted widget values into responses; return unanswered ids."""
    responses = st.session_state.responses
    unanswered: list[str] = []
    for item in items:
        choice = st.session_state.get(f"widget_{item.id}")
        if choice is None:
            unanswered.append(item.id)
        else:
            responses[item.id] = item.value_of(choice)
    return unanswered


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
def _page_intro() -> None:
    st.title("🧠 ADHD Screening Battery")
    st.write(
        "This assessment brings five validated questionnaires together in one "
        "sitting. You will move through them one section at a time, and you will "
        "get your scored feedback immediately at the end."
    )

    st.markdown(
        """
| Questionnaire | Items | What it looks at |
| --- | --- | --- |
| ASRS-v1.1 | 18 | Adult ADHD symptoms over the past 6 months |
| PSS-10 | 10 | Perceived stress over the last month |
| WHO-5 | 5 | Well-being over the last two weeks |
| rMEQ | 5 | Morning/evening chronotype |
| HSPS | 27 | Sensory processing sensitivity |
"""
    )
    st.caption("65 questions in total - most people finish in 10 to 15 minutes.")

    st.warning(
        "**This is a screening tool, not a diagnosis.** The results cannot "
        "diagnose ADHD or any other condition. If anything here concerns you, "
        "please discuss it with a qualified healthcare professional."
    )

    consent = st.checkbox(
        "I understand this is a screening tool and I consent to my responses "
        "being stored for review."
    )

    if st.button("Start assessment", type="primary", disabled=not consent):
        st.session_state.started_at = time.time()
        _goto(1)


GENDER_OPTIONS = ["Prefer not to say", "Female", "Male", "Non-binary", "Other"]


def _page_details() -> None:
    st.header("About you")
    st.caption("Your name and student ID are required. Everything else is optional.")

    participant = st.session_state.participant
    st.session_state.setdefault("w_full_name", participant.get("full_name", ""))
    st.session_state.setdefault("w_student_id", participant.get("student_id", ""))
    st.session_state.setdefault("w_email", participant.get("email", ""))
    st.session_state.setdefault("w_age", participant.get("age"))
    st.session_state.setdefault("w_gender", participant.get("gender", GENDER_OPTIONS[0]))
    st.session_state.setdefault("w_occupation", participant.get("occupation", ""))

    with st.form("form_details"):
        st.text_input("Full name", key="w_full_name")
        st.text_input(
            "Student ID",
            key="w_student_id",
            help="Your roll or enrolment number, so results can be matched to the "
            "class list.",
        )
        st.text_input("Email", key="w_email")

        col1, col2 = st.columns(2)
        col1.number_input(
            "Age", min_value=0, max_value=120, placeholder="Optional", key="w_age"
        )
        col2.selectbox("Gender", GENDER_OPTIONS, key="w_gender")
        st.text_input("Occupation", key="w_occupation")

        left, right = st.columns([1, 1])
        back = left.form_submit_button("Back", use_container_width=True)
        nxt = right.form_submit_button(
            "Next", type="primary", use_container_width=True
        )

    if not (back or nxt):
        return

    participant.update(
        {
            "full_name": st.session_state.w_full_name,
            "student_id": st.session_state.w_student_id,
            "email": st.session_state.w_email,
            "age": st.session_state.w_age,
            "gender": st.session_state.w_gender,
            "occupation": st.session_state.w_occupation,
        }
    )

    if back:
        _goto(st.session_state.page_index - 1)

    problems = []
    if not (participant.get("full_name") or "").strip():
        problems.append("your name")
    if not (participant.get("student_id") or "").strip():
        problems.append("your student ID")
    if problems:
        st.error(f"Please enter {' and '.join(problems)}.")
        return
    _goto(st.session_state.page_index + 1)


def _page_instrument(page: dict) -> None:
    inst = INSTRUMENTS[page["instrument"]]

    st.header(inst.short_name)
    if page["parts"] > 1:
        st.caption(
            f"Part {page['part']} of {page['parts']} - questions "
            f"{page['start']} to {page['end']} of {len(inst.items)}"
        )
    st.info(inst.instructions)
    if inst.anchors:
        st.caption(" · ".join(inst.anchors))

    items = _page_items(inst, page["start"], page["end"])

    with st.form(f"form_{inst.key}_{page['start']}_{page['end']}"):
        _render_items(items)
        left, right = st.columns([1, 1])
        back = left.form_submit_button("Back", use_container_width=True)
        nxt = right.form_submit_button(
            "Next", type="primary", use_container_width=True
        )

    if not (back or nxt):
        return

    # Save whatever was answered either way, so Back never loses work.
    unanswered = _harvest_items(items)

    if back:
        _goto(st.session_state.page_index - 1)
    if unanswered:
        st.error(
            f"Please answer every question - {len(unanswered)} still "
            "unanswered on this page."
        )
        return
    _goto(st.session_state.page_index + 1)


def _page_review() -> None:
    st.header("Review")
    responses = st.session_state.responses

    all_complete = True
    for page_index, page in enumerate(PAGES):
        if page["kind"] != "instrument":
            continue
        inst = INSTRUMENTS[page["instrument"]]
        item_ids = [
            item.id
            for item in inst.items
            if page["start"] <= item.number <= page["end"]
        ]
        missing = [i for i in item_ids if responses.get(i) is None]
        label = inst.short_name + (
            f" (part {page['part']})" if page["parts"] > 1 else ""
        )
        col1, col2 = st.columns([3, 1])
        if missing:
            all_complete = False
            col1.error(f"{label} - {len(missing)} unanswered")
        else:
            col1.success(f"{label} - complete")
        if col2.button("Edit", key=f"edit_{page_index}"):
            _goto(page_index)

    st.divider()
    st.session_state.setdefault(
        "w_notes", st.session_state.participant.get("notes", "")
    )
    st.text_area(
        "Anything you would like to add? (optional)",
        key="w_notes",
        placeholder="Context you would like whoever reviews this to know.",
    )

    if not all_complete:
        st.warning("Fill in the missing answers before submitting.")

    left, right = st.columns([1, 1])
    if left.button("Back", use_container_width=True):
        _goto(st.session_state.page_index - 1)
    if right.button(
        "Submit and see my results",
        type="primary",
        use_container_width=True,
        disabled=not all_complete,
    ):
        st.session_state.participant["notes"] = st.session_state.get("w_notes", "")
        results = score_all(responses)
        duration = int(time.time() - st.session_state.started_at)
        try:
            submission_id = db.save_submission(
                st.session_state.participant, responses, results, duration
            )
            st.session_state.submission_id = submission_id
            st.session_state.pop("save_error", None)
        except Exception as exc:  # never lose the user's feedback over a DB error
            st.session_state.submission_id = None
            st.session_state.save_error = str(exc)
        st.session_state.results = results
        st.session_state.celebrated = False
        _goto(st.session_state.page_index + 1)


_TONE_STYLE = {
    "good": ("✅", "success"),
    "neutral": ("•", "info"),
    "warn": ("⚠️", "warning"),
    "flag": ("🚩", "error"),
}


def _render_result(result: ScoreResult) -> None:
    icon, style = _TONE_STYLE.get(result.band.tone, ("•", "info"))
    with st.container(border=True):
        top, bottom = st.columns([1, 3])
        suffix = "%" if result.headline_label == "percentage" else ""
        top.metric(result.name, f"{result.headline}{suffix}")
        bottom.markdown(f"### {icon} {result.band.label}")
        bottom.write(result.band.detail)
        if not result.band.from_source:
            bottom.caption(
                "Interpretation band is the conventional one from the wider "
                "literature; the source questionnaire does not print cut-offs."
            )
        with st.expander("Details and scoring notes"):
            if result.metrics:
                st.write(result.metrics)
            for note in result.notes:
                st.markdown(f"- {note}")


def _page_results() -> None:
    results: dict[str, ScoreResult] = st.session_state.results or {}
    if not st.session_state.get("celebrated"):
        st.balloons()
        st.session_state.celebrated = True
    st.title("Your feedback")

    if st.session_state.get("save_error"):
        st.error(
            "Your results were scored but could not be saved to the database: "
            f"{st.session_state['save_error']}"
        )
    elif st.session_state.submission_id:
        st.success("Your responses have been recorded. Thank you for taking part.")

    st.warning(
        "**These results are a screening aid, not a diagnosis.** Only a qualified "
        "healthcare professional can diagnose ADHD or any other condition."
    )

    for key in ("asrs", "pss", "who5", "rmeq", "hsps"):
        if key in results:
            _render_result(results[key])

    st.divider()
    if st.session_state.submission_id:
        st.caption(f"Reference: `{st.session_state.submission_id}`")

    if st.button("Start a new assessment"):
        for key in (
            "page_index",
            "responses",
            "participant",
            "results",
            "submission_id",
            "save_error",
            "celebrated",
        ):
            st.session_state.pop(key, None)
        for state_key in list(st.session_state.keys()):
            if str(state_key).startswith(("widget_", "w_")):
                st.session_state.pop(state_key, None)
        st.rerun()


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def main() -> None:
    params = st.query_params

    # Health endpoint for the keep-alive pinger - render nothing heavy.
    if params.get("ping"):
        st.write("ok")
        return

    boot = _boot()
    if boot.get("db_error"):
        _page_db_error(boot["db_error"])
        return

    _init_state()

    if params.get("admin"):
        admin.render()
        return

    with st.sidebar:
        st.markdown("### ADHD Screening Battery")
        st.caption(
            "Five questionnaires, scored exactly as their source documents "
            "prescribe."
        )
        st.divider()
        st.link_button("Admin board", "?admin=1", use_container_width=True)

    _progress()
    page = PAGES[st.session_state.page_index]

    if page["kind"] == "intro":
        _page_intro()
    elif page["kind"] == "details":
        _page_details()
    elif page["kind"] == "instrument":
        _page_instrument(page)
    elif page["kind"] == "review":
        _page_review()
    elif page["kind"] == "results":
        _page_results()


if __name__ == "__main__":
    main()
