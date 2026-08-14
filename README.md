# ADHD Screening Battery

A single Streamlit front end that walks a participant through five questionnaires
one section at a time (OA style), scores each one exactly as its source document
prescribes, gives the participant immediate feedback, and stores everything in a
database that the admin board exports as one combined Excel workbook.

## What's included

| Questionnaire | Items | Scoring implemented |
| --- | --- | --- |
| **ASRS-v1.1** Adult ADHD Self-Report Scale | 18 | Part A shaded-box count; 4+ marks = symptoms highly consistent with adult ADHD |
| **PSS-10** Perceived Stress Scale | 10 | Items 4/5/7/8 reversed, summed 0–40, banded low / moderate / high |
| **WHO-5** Well-being Index | 5 | Raw 0–25, percentage = raw × 4 |
| **rMEQ** Morningness/Eveningness | 5 | Per-option weights summed, 4–25, evening → morning |
| **HSPS** Highly Sensitive Person Scale | 27 | 1–7 per item, summed 27–189 |

65 questions total, roughly 10–15 minutes to complete.

### Built for a whole cohort sitting it at once

Each page's questions live inside an `st.form`, so answering a question does not
round-trip to the server — the page is submitted in one go. That is **8 script
reruns per participant instead of 65**, which is what keeps the app responsive
when a full class starts at the same time. Streamlit runs each session's script
in its own thread inside one process, so per-click reruns are the thing that
actually bites at that concurrency.

### A note on the ASRS shading

The ASRS screener counts responses that land in the "darkly shaded boxes" of the
printed form. Those thresholds were read directly off the shading in the source
PDF rather than from memory:

* **Part A** — items 1–3 count from *Sometimes* upward, items 4–6 from *Often* upward.
  4 or more shaded marks is a positive screen.
* **Part B** — items 9, 12, 16 and 18 count from *Sometimes* upward, the rest from
  *Often* upward. Part B has no total score and no diagnostic likelihood; it is
  reported as additional cues only, exactly as the source instructs.

### Interpretation bands

Every band that the source PDF prints is implemented verbatim. Three instruments
(WHO-5, rMEQ, HSPS) publish no numeric cut-offs in the supplied PDFs, so the
conventional bands from the wider literature are used and are **explicitly
labelled in the UI** as not coming from the source document.

## Quick start

```bash
pip install -r requirements.txt
export ADMIN_KEY="choose-a-strong-key"
streamlit run app.py
```

The participant flow is at `/`. The admin board is at `/?admin=1`.

## Configuration

All configuration is by environment variable (or Streamlit secrets for `ADMIN_KEY`).

| Variable | Default | Purpose |
| --- | --- | --- |
| `ADMIN_KEY` | *(unset)* | **Required for the admin board.** Without it the board stays locked. |
| `DATABASE_URL` | *(unset)* | Postgres connection string. Falls back to SQLite when unset. |
| `DB_PATH` | `data/submissions.db` | SQLite file path, used only when `DATABASE_URL` is unset. |
| `SELF_PING_URL` | *(unset)* | Public URL of this app. Setting it enables the keep-alive pinger. |
| `SELF_PING_INTERVAL` | `600` | Seconds between self-pings (minimum 60). |

### Persistence

SQLite is the zero-config default and is fine for local use. **Hosted containers
have ephemeral disks**, so on Streamlit Community Cloud, Render or Railway a
restart wipes a SQLite file. For anything you need to keep, point `DATABASE_URL`
at a managed Postgres (Supabase, Neon, RDS) and uncomment `psycopg2-binary` in
`requirements.txt`.

> **Collecting data you cannot re-collect?** Use Postgres. If you are running
> this once with a cohort, a container recycle on SQLite loses every submission
> and the session cannot be repeated. No code change is needed — set
> `DATABASE_URL` and the app uses it.

The schema self-migrates: missing columns are added with `ALTER TABLE` on
startup, so upgrading the app over an existing database does not require
dropping it.

### Keep-alive

Free tiers idle an app to sleep after a period without traffic. Set
`SELF_PING_URL` to the app's own public URL and a daemon thread will request
`?ping=1` on an interval to keep the container warm. `?ping=1` renders a tiny
health response rather than the full questionnaire, so the ping is cheap. The
admin board shows ping count, last status and last ping time.

Note that this keeps a *running* container awake; it cannot wake a container that
a host has already stopped. If your host suspends by schedule rather than by
idleness, use an external uptime monitor instead.

## Admin board

Go to `/?admin=1` and enter the admin key. The key is compared with
`hmac.compare_digest`, and the board refuses to unlock at all when `ADMIN_KEY`
is unset. The board provides:

* Summary metrics — total submissions, ASRS screen-positive rate, high-stress
  count, low-well-being count.
* A sortable submissions table, with filters for date range, screen-positive
  only, and name/email search.
* **Download combined Excel** — respects the active filters.
* Per-submission drill-down showing every question, the chosen answer and its
  score, plus a confirmed delete.
* Keep-alive status.

### The Excel workbook

| Sheet | Contents |
| --- | --- |
| `Combined` | One row per submission: participant details + every score + all 65 raw item answers. This is the main sheet. |
| `Scores Summary` | Participant details and scores only. |
| `Responses (labelled)` | Each answer as `value - label` for human reading. |
| `ASRS-v1.1`, `PSS-10`, `WHO-5`, `rMEQ`, `HSPS` | One sheet per instrument. |
| `Codebook` | Every item id, question text and response-option mapping. |
| `Scoring Rules` | The scoring rule for each instrument, as printed in its source PDF. |

## Deployment

**Streamlit Community Cloud** — point it at this repo with `app.py` as the entry
point, then add `ADMIN_KEY` (and `DATABASE_URL`, `SELF_PING_URL`) under
*Settings → Secrets*.

**Render / Railway / Fly** — build with `pip install -r requirements.txt`, start with:

```bash
streamlit run app.py --server.port $PORT --server.address 0.0.0.0
```

Set the environment variables in the dashboard.

## Tests

```bash
python -m pytest tests/ -q
```

28 tests cover the scoring rules, including the ASRS shading thresholds, the PSS
reversal and band boundaries, and the documented score ranges for every
instrument.

## Project layout

```
app.py                     Streamlit wizard (participant flow + routing)
assessment/
  instruments.py           All 65 items, response options and score weights
  scoring.py               Scoring rules and interpretation bands
  db.py                    SQLAlchemy storage (SQLite or Postgres)
  excel.py                 Combined multi-sheet workbook builder
  admin.py                 Admin board, gated by ADMIN_KEY
  keepalive.py             Self-ping background thread
tests/test_scoring.py      Scoring tests
```

## Disclaimer

This tool is a screening aid and does not diagnose ADHD or any other condition.
Both the intro and the results page state this. The questionnaires are
reproduced from their published sources for screening use; check the licensing
terms of each instrument before deploying commercially.
