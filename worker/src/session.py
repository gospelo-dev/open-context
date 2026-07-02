"""
Cookie-based session management (browser login for the OAuth consent screen).

Sessions store the authenticated GitHub identity (user_sub + login). Stored in
KV with TTL; the session ID is sent to the browser as an HttpOnly cookie.
"""

import json
import secrets
from typing import Optional

SESSION_COOKIE_NAME = "oc_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days


def _kv_key(session_id: str) -> str:
    return f"session:{session_id}"


async def create_session(kv, user_sub: str, login: str) -> str:
    """Create a new session and return the session ID."""
    session_id = secrets.token_urlsafe(32)
    payload = {"user_sub": user_sub, "login": login}
    await kv.put(
        _kv_key(session_id),
        json.dumps(payload),
        {"expirationTtl": SESSION_TTL_SECONDS},
    )
    return session_id


async def get_session(kv, session_id: str) -> Optional[dict]:
    """Look up a session by ID. Returns None if not found or expired."""
    if not session_id:
        return None
    raw = await kv.get(_kv_key(session_id))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


async def destroy_session(kv, session_id: str) -> None:
    """Delete a session from KV."""
    if not session_id:
        return
    await kv.delete(_kv_key(session_id))


def parse_cookie_header(cookie_header: Optional[str]) -> dict:
    """Parse a Cookie header into a dict."""
    if not cookie_header:
        return {}
    out = {}
    for part in cookie_header.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def session_cookie_value(session_id: str) -> str:
    """Build a Set-Cookie header value for an authenticated session."""
    return (
        f"{SESSION_COOKIE_NAME}={session_id}; "
        f"Path=/; HttpOnly; Secure; SameSite=Lax; "
        f"Max-Age={SESSION_TTL_SECONDS}"
    )


def clear_session_cookie() -> str:
    """Build a Set-Cookie header value that clears the session cookie."""
    return (
        f"{SESSION_COOKIE_NAME}=; "
        f"Path=/; HttpOnly; Secure; SameSite=Lax; "
        f"Max-Age=0"
    )


def session_id_from_request(request) -> Optional[str]:
    """Extract the session ID from the request's Cookie header."""
    cookie_header = request.headers.get("Cookie") or request.headers.get("cookie")
    cookies = parse_cookie_header(cookie_header)
    return cookies.get(SESSION_COOKIE_NAME)
