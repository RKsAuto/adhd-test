"""Identify exactly what is running.

A deployed app silently serving an older commit is hard to spot from the
outside and wastes a lot of time: you fix something, redeploy, and see the
old behaviour because the host is tracking a branch that never received the
fix. The admin board shows this so the question is answerable in one glance.
"""

from __future__ import annotations

import os
import subprocess
import sys
from functools import lru_cache


@lru_cache(maxsize=1)
def git_revision() -> dict[str, str]:
    """Best-effort description of the checked-out commit."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def run(*args: str) -> str:
        try:
            return subprocess.run(
                args,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout.strip()
        except Exception:
            return ""

    return {
        "commit": run("git", "rev-parse", "--short", "HEAD") or "unknown",
        "branch": run("git", "rev-parse", "--abbrev-ref", "HEAD") or "unknown",
        "subject": run("git", "log", "-1", "--pretty=%s") or "unknown",
        "committed": run("git", "log", "-1", "--pretty=%cI") or "unknown",
    }


def python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
