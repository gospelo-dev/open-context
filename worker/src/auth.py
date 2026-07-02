"""
GitHub OAuth 2.0 flow (browser login backing the MCP OAuth consent screen).

The GitHub access token obtained here IS the per-user credential: it is stored
encrypted and later used to call the GitHub API on the user's behalf.

    GET  /auth/login     Redirect to GitHub OAuth consent
    GET  /auth/callback  Receive code, exchange for token, identify user
    GET/POST /auth/logout  Destroy session

Required Worker Secrets:
    GITHUB_OAUTH_CLIENT_ID
    GITHUB_OAUTH_CLIENT_SECRET
"""

import json
import secrets
import urllib.parse
from typing import Optional

import js
from pyodide.ffi import to_js
from workers import Response

import session as session_mod

GITHUB_AUTH_ENDPOINT = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_ENDPOINT = "https://github.com/login/oauth/access_token"
GITHUB_USER_ENDPOINT = "https://api.github.com/user"
# read:user lets us read the identity; public repos are readable regardless.
# (A future private-repo phase would request `repo` here.)
GITHUB_SCOPES = "read:user"

OAUTH_STATE_COOKIE = "oc_oauth_state"
OAUTH_RETURN_TO_COOKIE = "oc_oauth_return_to"
OAUTH_STATE_TTL_SECONDS = 600  # 10 min


def _redirect_uri(request_url: str) -> str:
    parsed = urllib.parse.urlparse(request_url)
    return f"{parsed.scheme}://{parsed.netloc}/auth/callback"


def _cookie(name: str, value: str, max_age: int) -> str:
    return (
        f"{name}={value}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age={max_age}"
    )


def _is_safe_return_to(value: str, request_url: str) -> bool:
    """Same-origin absolute URL OR site-relative path (prevents open redirect)."""
    if not value:
        return False
    if value.startswith("/") and not value.startswith("//"):
        return True
    try:
        target = urllib.parse.urlparse(value)
        here = urllib.parse.urlparse(request_url)
    except ValueError:
        return False
    if target.scheme not in ("http", "https"):
        return False
    return target.scheme == here.scheme and target.netloc == here.netloc


async def handle_login(request, env) -> Response:
    """GET /auth/login - begin GitHub OAuth flow."""
    client_id = getattr(env, "GITHUB_OAUTH_CLIENT_ID", None)
    if not client_id:
        return Response("OAuth not configured: GITHUB_OAUTH_CLIENT_ID missing", status=500)

    state = secrets.token_urlsafe(32)
    redirect_uri = _redirect_uri(request.url)

    parsed = urllib.parse.urlparse(request.url)
    qs = dict(urllib.parse.parse_qsl(parsed.query))
    return_to = qs.get("return_to") or ""
    safe_return_to = return_to if _is_safe_return_to(return_to, request.url) else ""

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": GITHUB_SCOPES,
        "state": state,
        "allow_signup": "true",
    }
    auth_url = f"{GITHUB_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"

    headers = js.Headers.new()
    headers.append("Location", auth_url)
    headers.append("Set-Cookie", _cookie(OAUTH_STATE_COOKIE, state, OAUTH_STATE_TTL_SECONDS))
    if safe_return_to:
        headers.append(
            "Set-Cookie",
            _cookie(OAUTH_RETURN_TO_COOKIE, urllib.parse.quote(safe_return_to, safe=""), OAUTH_STATE_TTL_SECONDS),
        )
    else:
        headers.append("Set-Cookie", _cookie(OAUTH_RETURN_TO_COOKIE, "", 0))

    return Response("", status=302, headers=headers)


async def handle_callback(request, env) -> Response:
    """GET /auth/callback - exchange code for a GitHub token, identify user, create session."""
    client_id = getattr(env, "GITHUB_OAUTH_CLIENT_ID", None)
    client_secret = getattr(env, "GITHUB_OAUTH_CLIENT_SECRET", None)
    kv = getattr(env, "AUTH_KV", None)

    if not client_id or not client_secret:
        return Response("OAuth not configured", status=500)
    if kv is None:
        return Response("AUTH_KV namespace not bound", status=500)

    parsed = urllib.parse.urlparse(request.url)
    qs = dict(urllib.parse.parse_qsl(parsed.query))
    code = qs.get("code")
    state = qs.get("state")
    error = qs.get("error")

    if error:
        return Response(f"OAuth error from GitHub: {error}", status=400)
    if not code or not state:
        return Response("Missing code or state in callback", status=400)

    cookies = session_mod.parse_cookie_header(
        request.headers.get("Cookie") or request.headers.get("cookie")
    )
    expected_state = cookies.get(OAUTH_STATE_COOKIE)
    if not expected_state or expected_state != state:
        return Response("State mismatch (possible CSRF)", status=400)

    raw_return_to = cookies.get(OAUTH_RETURN_TO_COOKIE) or ""
    decoded_return_to = urllib.parse.unquote(raw_return_to) if raw_return_to else ""
    final_return_to = (
        decoded_return_to if _is_safe_return_to(decoded_return_to, request.url) else "/"
    )

    # Exchange code for a GitHub access token.
    body = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": _redirect_uri(request.url),
    })
    init = to_js({
        "method": "POST",
        "headers": {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        "body": body,
    })
    resp = await js.fetch(GITHUB_TOKEN_ENDPOINT, init)
    if not resp.ok:
        text = await resp.text()
        return Response(f"Token exchange failed: {text}", status=502)
    token_data = json.loads(await resp.text())
    access_token = token_data.get("access_token")
    if not access_token:
        return Response(f"No access_token in GitHub response: {token_data}", status=502)

    # Identify the user.
    user_init = to_js({
        "method": "GET",
        "headers": {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "gospelo-open-context",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    })
    user_resp = await js.fetch(GITHUB_USER_ENDPOINT, user_init)
    if not user_resp.ok:
        text = await user_resp.text()
        return Response(f"Failed to read GitHub user: {text}", status=502)
    user = json.loads(await user_resp.text())
    user_sub = str(user.get("id") or "")
    login = user.get("login") or ""
    if not user_sub:
        return Response("GitHub user response missing id", status=502)

    import user_store
    await user_store.save_github_token(env, kv, user_sub, login, access_token)

    session_id = await session_mod.create_session(kv, user_sub, login)

    headers = js.Headers.new()
    headers.append("Location", final_return_to)
    headers.append("Set-Cookie", session_mod.session_cookie_value(session_id))
    headers.append("Set-Cookie", _cookie(OAUTH_STATE_COOKIE, "", 0))
    headers.append("Set-Cookie", _cookie(OAUTH_RETURN_TO_COOKIE, "", 0))
    return Response("", status=302, headers=headers)


async def handle_logout(request, env) -> Response:
    """GET/POST /auth/logout - destroy the session."""
    kv = getattr(env, "AUTH_KV", None)
    sid = session_mod.session_id_from_request(request)
    if kv is not None and sid:
        await session_mod.destroy_session(kv, sid)
    return Response(
        "",
        status=302,
        headers={"Location": "/", "Set-Cookie": session_mod.clear_session_cookie()},
    )


async def require_session(request, env) -> Optional[dict]:
    """Return the active session payload or None if unauthenticated."""
    kv = getattr(env, "AUTH_KV", None)
    if kv is None:
        return None
    sid = session_mod.session_id_from_request(request)
    if not sid:
        return None
    return await session_mod.get_session(kv, sid)
