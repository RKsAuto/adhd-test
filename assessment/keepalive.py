"""Self-ping keep-alive.

Free hosting tiers put an app to sleep after a period without traffic. This
module starts one background thread that requests the app's own public URL on
an interval so the container keeps seeing requests.

Configure with environment variables:

    SELF_PING_URL       full public URL of the app (required to enable)
    SELF_PING_INTERVAL  seconds between pings (default 600)

What this actually does, measured rather than assumed: a plain HTTP GET to a
Streamlit app returns the static front-end shell. The Python script runs only
when a browser opens a websocket session, so this ping does NOT execute the
app or create a Streamlit session - it generates HTTP traffic to the
container and nothing more. That is enough for hosts that idle on request
activity (Render, Railway). Whether Streamlit Community Cloud's own
inactivity logic counts it is not something this code can guarantee.

It also cannot wake a container the host has already stopped, since there is
nothing running to send the request. Treat it as a cheap hedge, not a
guarantee: to be certain an app is warm for a known event, open it in a
browser a few minutes beforehand.

The ``?ping=1`` parameter is still useful as a fast manual health check -
opened in a browser it renders "ok" without touching the database.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from urllib.parse import urlencode, urlparse, urlunparse

import requests

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL = 600
_thread: threading.Thread | None = None
_lock = threading.Lock()

_state: dict[str, object] = {
    "enabled": False,
    "url": None,
    "interval": DEFAULT_INTERVAL,
    "last_ping": None,
    "last_status": None,
    "ping_count": 0,
    "error_count": 0,
}


def _ping_url(base_url: str) -> str:
    parts = urlparse(base_url)
    query = urlencode({"ping": "1"})
    return urlunparse(parts._replace(query=query))


def _loop(url: str, interval: int) -> None:
    target = _ping_url(url)
    # Stagger the first ping so a cold start is not competing with real traffic.
    time.sleep(min(interval, 60))
    while True:
        try:
            response = requests.get(target, timeout=20)
            _state["last_status"] = response.status_code
            _state["ping_count"] = int(_state["ping_count"]) + 1
        except Exception as exc:  # network hiccups must never kill the thread
            _state["last_status"] = f"error: {exc.__class__.__name__}"
            _state["error_count"] = int(_state["error_count"]) + 1
            logger.warning("self-ping failed: %s", exc)
        finally:
            _state["last_ping"] = time.time()
        time.sleep(interval)


def start() -> dict[str, object]:
    """Start the keep-alive thread once per process. Safe to call repeatedly."""
    global _thread

    url = os.environ.get("SELF_PING_URL", "").strip()
    if not url:
        _state["enabled"] = False
        return dict(_state)

    try:
        interval = max(60, int(os.environ.get("SELF_PING_INTERVAL", DEFAULT_INTERVAL)))
    except ValueError:
        interval = DEFAULT_INTERVAL

    with _lock:
        if _thread is not None and _thread.is_alive():
            return dict(_state)
        _state.update({"enabled": True, "url": url, "interval": interval})
        _thread = threading.Thread(
            target=_loop, args=(url, interval), name="self-ping", daemon=True
        )
        _thread.start()
        logger.info("self-ping started for %s every %ss", url, interval)

    return dict(_state)


def status() -> dict[str, object]:
    return dict(_state)
