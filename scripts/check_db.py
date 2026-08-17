#!/usr/bin/env python3
"""Check a database connection string before putting it into a host's secrets.

Usage:
    python scripts/check_db.py "postgresql://user:pass@host:5432/dbname"
    DATABASE_URL="..." python scripts/check_db.py

Prints a verdict and, when it fails, the most likely reason. The password is
never printed. Run this locally: it turns a deploy-reboot-retry loop into a
two second check.
"""

from __future__ import annotations

import os
import socket
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main() -> int:
    url = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DATABASE_URL", "")).strip()
    if not url:
        print("No connection string given.")
        print(__doc__)
        return 2

    os.environ["DATABASE_URL"] = url

    try:
        from sqlalchemy.engine import make_url
    except ImportError:
        print("SQLAlchemy is not installed. Run: pip install -r requirements.txt")
        return 2

    normalised = url.replace("postgres://", "postgresql://", 1)
    try:
        parsed = make_url(normalised)
    except Exception as exc:
        print(f"FAIL  the string could not be parsed: {exc}")
        return 1

    host = parsed.host or ""
    port = parsed.port or 5432
    print(f"host      {host}")
    print(f"port      {port}")
    print(f"database  {parsed.database}")
    print(f"username  {parsed.username}")
    print(f"password  {'set' if parsed.password else 'MISSING'}")
    print()

    placeholder = (parsed.password or "").strip("[]").upper() in {
        "YOUR-PASSWORD",
        "YOUR_PASSWORD",
        "PASSWORD",
    }
    if placeholder:
        print("FAIL  the password is still the placeholder from the docs.")
        print("      Paste your real database password in its place.")
        return 1

    # A URL with no host is a local unix socket, where a password is optional.
    if host and not parsed.password:
        print("FAIL  no password. Replace the [YOUR-PASSWORD] placeholder.")
        return 1

    if host.startswith("db.") and host.endswith(".supabase.co"):
        print("FAIL  this is Supabase's DIRECT host, which is IPv6-only.")
        print("      Streamlit Cloud has no IPv6 and can never reach it.")
        print("      Use the Session pooler host instead:")
        ref = host.removeprefix("db.").removesuffix(".supabase.co")
        print(f"      postgresql://postgres.{ref}:<PASSWORD>"
              "@aws-0-<REGION>.pooler.supabase.com:5432/postgres")
        return 1

    # Does the host have an IPv4 address at all? This is the exact failure the
    # deployed app hit ("No address associated with hostname").
    try:
        ipv4 = socket.getaddrinfo(host, port, socket.AF_INET)
        print(f"IPv4      yes ({ipv4[0][4][0]})")
    except socket.gaierror:
        print("IPv4      NO -- host does not resolve to an IPv4 address.")
        print("FAIL  a host with no IPv4 record cannot be reached from")
        print("      Streamlit Cloud. Use a pooler/IPv4 endpoint.")
        return 1
    except Exception as exc:
        print(f"IPv4      could not check ({type(exc).__name__})")

    if "pooler.supabase.com" in host and port == 6543:
        print()
        print("NOTE  port 6543 is the transaction pooler. Prefer the session")
        print("      pooler on port 5432 for this app -- it keeps a connection")
        print("      pool open and session mode is the better fit.")

    print()
    try:
        from assessment import db

        ok, message = db.check_connection()
    except Exception as exc:
        print(f"FAIL  {type(exc).__name__}: {exc}")
        return 1

    if ok:
        print("OK    connected and the schema is in place.")
        try:
            print(f"      {db.count_submissions()} submission(s) currently stored.")
        except Exception:
            pass
        return 0

    print(f"FAIL  {message}")
    print()
    print("Common causes:")
    print("  * database paused (free projects idle out -- open the dashboard)")
    print("  * wrong password")
    print("  * password contains @ / : or # and is not percent-encoded")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
