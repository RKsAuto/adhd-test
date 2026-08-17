# Deployment

Written for the case this was built for: a cohort sitting the battery once, where
the data cannot be re-collected.

Order matters — **create the database before deploying the app**, so the app
never starts on SQLite and quietly collects submissions onto a disk that will be
wiped.

---

## 1. Create the Postgres database (do this first)

Either free tier is plenty; 80 submissions is a rounding error against both.

**Supabase** — New project → wait for provisioning → *Project Settings →
Database → Connection string → URI*. Use the **Session pooler** URI (port 5432).
Replace `[YOUR-PASSWORD]` with the database password you set.

**Neon** — New project → *Dashboard → Connection Details → Connection string*.

You end up with something like:

```
postgresql://user:password@host:5432/dbname
```

`postgres://`-style URLs also work; the app rewrites the scheme.

> Treat this string as a password. Put it straight into the host's secrets UI —
> don't paste it into chat, a commit, or a shared doc.

## 2. Generate an admin key

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Anyone with this key can read and export every submission, including names and
student IDs. Keep it out of the repo and off shared slides.

## 3. Deploy

### Streamlit Community Cloud

1. Push this repo to GitHub (already done on your branch).
2. share.streamlit.io → **New app** → pick the repo, branch, and `app.py`.
3. Before the first run, open **Advanced settings → Secrets** and paste:

   ```toml
   ADMIN_KEY = "the-key-you-generated"
   DATABASE_URL = "postgresql://user:password@host:5432/dbname"
   ```

4. Deploy. Once you have the public URL, add it to Secrets and reboot:

   ```toml
   SELF_PING_URL = "https://your-app.streamlit.app"
   SELF_PING_INTERVAL = "600"
   ```

Community Cloud apps are **publicly reachable by default** — anyone with the
link can open the questionnaire. That is usually what you want for a class, but
it does mean the URL is the only thing standing between the public and your form.
The admin board stays protected by `ADMIN_KEY` regardless.

### Render

New **Web Service** → connect the repo →

* Build: `pip install -r requirements.txt`
* Start: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`
* Environment: `ADMIN_KEY`, `DATABASE_URL`, and after the first deploy
  `SELF_PING_URL`.

Render's free tier sleeps after 15 minutes idle. The self-ping keeps a *running*
container warm but cannot wake a stopped one, so either use a paid instance for
the session or open the app a few minutes before the class starts.

## 4. Verify before the class (five minutes, do not skip)

1. Open `/?admin=1` and unlock with your key.
2. **Confirm there is no red storage banner.** If you see one, `DATABASE_URL`
   has not reached the app and you are on ephemeral SQLite — fix that before
   anyone submits.
3. Complete one full assessment yourself on a phone.
4. Back in the admin board: your submission appears, and **Download combined
   Excel** opens with your answers in the `Combined` sheet.
5. Reboot the app from the host's dashboard, then reload the admin board. Your
   test submission should still be there. **This is the test that proves
   persistence works** — if the row vanished, you are on SQLite.
6. Delete the test submission.

## 5. On the day

* Have the URL ready as a link or QR code; the form is mobile-friendly.
* Warm the app a few minutes before, so the first student doesn't wait on a
  cold start.
* Export the workbook at the end of the session, and again afterwards. The
  export is filtered by whatever filters are active, so clear them for the
  full set.

## Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `ADMIN_KEY` | Yes | Unlocks the admin board. Board stays locked if unset. |
| `DATABASE_URL` | Strongly recommended | Postgres connection string. Falls back to SQLite when unset. |
| `DB_PATH` | No | SQLite path, used only when `DATABASE_URL` is unset. |
| `SELF_PING_URL` | No | This app's public URL; enables the keep-alive thread. |
| `SELF_PING_INTERVAL` | No | Seconds between pings, default 600, minimum 60. |

Streamlit secrets are mirrored into the environment at startup, so either
mechanism works. Real environment variables take precedence.

## Troubleshooting

**Red storage banner on the admin board.** `DATABASE_URL` isn't reaching the
app. Check for typos in the secrets UI, that you saved and rebooted, and that
the value has no surrounding quotes-inside-quotes.

**`ModuleNotFoundError: psycopg2`.** The host installed from a stale
`requirements.txt`; `psycopg2-binary` is a default dependency here. Clear the
build cache and redeploy.

**Connection refused / timeout to Postgres.** Supabase: use the pooler URI, not
the direct one. Check the database isn't paused — free projects idle out after a
period of inactivity, so open the dashboard before class.

**Admin board says no key is configured.** `ADMIN_KEY` is unset. The board
refuses to unlock rather than defaulting to something guessable.

**A student lost their progress.** Progress lives in server memory, so a
container restart or a closed tab sends them back to the start. Nothing to
recover — have them retake it, and delete the partial row if one exists.
