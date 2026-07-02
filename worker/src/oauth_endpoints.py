"""
OAuth 2.1 authorization server endpoints (MCP-client-facing).

Public-client / PKCE flow used by Claude Code, Codex, Cursor, etc.:

    GET  /.well-known/oauth-authorization-server   RFC 8414 metadata
    GET  /.well-known/oauth-protected-resource     RFC 9728 metadata
    POST /oauth/register                           RFC 7591 dynamic registration
    GET  /oauth/authorize                          RFC 6749 + RFC 7636 (S256)
    POST /oauth/authorize/grant                    consent form submission
    POST /oauth/token                              code -> Bearer access token

Tokens are opaque (KV-backed lookup). The consent screen is gated by a GitHub
browser login (auth.py); granting binds the MCP token to that GitHub identity.
"""

import hashlib
import json
import urllib.parse
from base64 import urlsafe_b64encode
from typing import Optional

from workers import Response

import auth
import oauth_store

SCOPES_SUPPORTED = ["mcp:read", "mcp:tools"]
SCOPE_DESCRIPTIONS = {
    "mcp:read": "Read package documentation trees and files",
    "mcp:tools": "Call the docs/source retrieval tools",
}


def _origin(request_url: str) -> str:
    parsed = urllib.parse.urlparse(request_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _canonical_resource(request) -> str:
    return f"{_origin(request.url)}/mcp"


def _json_response(data: dict, status: int = 200, extra_headers: Optional[dict] = None) -> Response:
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
        "Access-Control-Allow-Origin": "*",
    }
    if extra_headers:
        headers.update(extra_headers)
    return Response(json.dumps(data, ensure_ascii=False), status=status, headers=headers)


def _html_response(html: str, status: int = 200) -> Response:
    return Response(
        html,
        status=status,
        headers={"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
    )


def _oauth_error(error: str, description: str = "", status: int = 400) -> Response:
    payload = {"error": error}
    if description:
        payload["error_description"] = description
    return _json_response(payload, status=status)


async def _read_form_or_json(request) -> dict:
    body_text = await request.text()
    content_type = (request.headers.get("Content-Type") or "").lower()
    if "application/json" in content_type:
        try:
            return json.loads(body_text or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}
    out: dict = {}
    for part in body_text.split("&"):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
        else:
            k, v = part, ""
        out[urllib.parse.unquote_plus(k)] = urllib.parse.unquote_plus(v)
    return out


def _is_valid_redirect_uri(uri: str) -> bool:
    """Allow only http://127.0.0.1:*, http://localhost:*, and https://*."""
    if not uri or not isinstance(uri, str):
        return False
    try:
        parsed = urllib.parse.urlparse(uri)
    except ValueError:
        return False
    if not parsed.scheme or not parsed.hostname:
        return False
    if parsed.scheme == "https":
        return True
    if parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost"):
        return True
    return False


def _verify_pkce_s256(code_verifier: str, code_challenge: str) -> bool:
    """RFC 7636: BASE64URL-NO-PAD(SHA256(code_verifier)) == code_challenge."""
    if not code_verifier or not code_challenge:
        return False
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    expected = urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    if len(expected) != len(code_challenge):
        return False
    diff = 0
    for a, b in zip(expected, code_challenge):
        diff |= ord(a) ^ ord(b)
    return diff == 0


def _iso_to_epoch(iso: str) -> float:
    from datetime import datetime, timezone
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (ValueError, TypeError):
        return 0


# --- Metadata --------------------------------------------------------------


async def handle_authorization_server_metadata(request, env) -> Response:
    issuer = _origin(request.url)
    return _json_response({
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "registration_endpoint": f"{issuer}/oauth/register",
        "scopes_supported": SCOPES_SUPPORTED,
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    })


async def handle_protected_resource_metadata(request, env) -> Response:
    issuer = _origin(request.url)
    return _json_response({
        "resource": f"{issuer}/mcp",
        "authorization_servers": [issuer],
        "scopes_supported": SCOPES_SUPPORTED,
        "bearer_methods_supported": ["header"],
    })


# --- Dynamic Client Registration (RFC 7591) --------------------------------


async def handle_register(request, env) -> Response:
    kv = getattr(env, "AUTH_KV", None)
    if kv is None:
        return _oauth_error("server_error", "AUTH_KV not bound", status=500)

    body = await _read_form_or_json(request)
    redirect_uris = body.get("redirect_uris") or []
    if isinstance(redirect_uris, str):
        redirect_uris = [redirect_uris]
    if not isinstance(redirect_uris, list) or not redirect_uris:
        return _oauth_error("invalid_redirect_uri", "redirect_uris must be a non-empty array")
    for uri in redirect_uris:
        if not _is_valid_redirect_uri(uri):
            return _oauth_error("invalid_redirect_uri", f"redirect_uri not allowed: {uri}")

    client_name = body.get("client_name")
    if client_name is not None and not isinstance(client_name, str):
        client_name = str(client_name)

    requested_method = body.get("token_endpoint_auth_method")
    if requested_method and requested_method != "none":
        return _oauth_error(
            "invalid_client_metadata",
            "Only public clients (token_endpoint_auth_method=none) are supported",
        )

    record = await oauth_store.create_client(kv, redirect_uris=redirect_uris, client_name=client_name)
    return _json_response({
        "client_id": record["client_id"],
        "client_id_issued_at": int(_iso_to_epoch(record["created_at"])),
        "redirect_uris": record["redirect_uris"],
        "grant_types": record["grant_types"],
        "response_types": record["response_types"],
        "token_endpoint_auth_method": record["token_endpoint_auth_method"],
        "client_name": record.get("client_name"),
        "scope": record["scope"],
    }, status=201)


# --- Authorization endpoint (consent) --------------------------------------


def _normalize_scope(requested: str, client_default: str) -> str:
    src = (requested or client_default or "").split()
    allowed = [s for s in src if s in SCOPES_SUPPORTED]
    if not allowed:
        return " ".join(SCOPES_SUPPORTED)
    seen = set()
    out = []
    for s in allowed:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return " ".join(out)


def _redirect_with_error(redirect_uri: str, state: str, error: str, description: str = "") -> Response:
    params = {"error": error}
    if description:
        params["error_description"] = description
    if state:
        params["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    return Response("", status=302, headers={"Location": f"{redirect_uri}{sep}{urllib.parse.urlencode(params)}"})


def _esc(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _html_error_page(error: str, description: str, status: int = 400) -> Response:
    html = (
        f"<!doctype html><meta charset=utf-8><title>Authorization error</title>"
        f"<body style='font-family:system-ui;max-width:36rem;margin:4rem auto;padding:0 1rem'>"
        f"<h1 style='color:#b91c1c'>Authorization error</h1>"
        f"<p><strong>{_esc(error)}</strong></p><p>{_esc(description)}</p></body>"
    )
    return _html_response(html, status=status)


def _render_consent(client_name, client_id, redirect_uri, scope, code_challenge,
                    code_challenge_method, state, resource, login, request_url) -> Response:
    scope_items = "".join(
        f"<li><code>{_esc(s)}</code> — {_esc(SCOPE_DESCRIPTIONS.get(s, s))}</li>"
        for s in scope.split()
    )
    hidden = "".join(
        f"<input type=hidden name='{_esc(k)}' value='{_esc(v)}'>"
        for k, v in [
            ("client_id", client_id), ("redirect_uri", redirect_uri), ("scope", scope),
            ("code_challenge", code_challenge), ("code_challenge_method", code_challenge_method),
            ("state", state), ("resource", resource),
        ]
    )
    html = (
        f"<!doctype html><meta charset=utf-8><title>Authorize {_esc(client_name)}</title>"
        f"<body style='font-family:system-ui;max-width:36rem;margin:4rem auto;padding:0 1rem'>"
        f"<h1>Authorize access</h1>"
        f"<p><strong>{_esc(client_name)}</strong> wants to access <strong>gospelo-open-context</strong> "
        f"as GitHub user <strong>{_esc(login)}</strong>.</p>"
        f"<ul>{scope_items}</ul>"
        f"<p style='color:#555'>Requests to GitHub will use your account's rate limit.</p>"
        f"<form method=post action='/oauth/authorize/grant'>{hidden}"
        f"<button name=decision value=allow style='padding:.6rem 1.2rem;font-size:1rem;background:#0d9488;color:#fff;border:0;border-radius:6px;cursor:pointer'>Allow</button> "
        f"<button name=decision value=deny style='padding:.6rem 1.2rem;font-size:1rem;background:#e5e7eb;border:0;border-radius:6px;cursor:pointer'>Deny</button>"
        f"</form>"
        f"<p style='margin-top:1rem'><a href='/auth/logout'>Use a different GitHub account</a></p>"
        f"</body>"
    )
    return _html_response(html)


async def handle_authorize(request, env) -> Response:
    kv = getattr(env, "AUTH_KV", None)
    if kv is None:
        return _html_response("AUTH_KV not bound", status=500)

    parsed = urllib.parse.urlparse(request.url)
    qs = dict(urllib.parse.parse_qsl(parsed.query))
    response_type = qs.get("response_type", "")
    client_id = qs.get("client_id", "")
    redirect_uri = qs.get("redirect_uri", "")
    scope_param = qs.get("scope", "")
    code_challenge = qs.get("code_challenge", "")
    code_challenge_method = qs.get("code_challenge_method", "")
    state = qs.get("state", "")
    resource_param = qs.get("resource", "")

    if not client_id:
        return _html_error_page("invalid_request", "client_id is required.")
    client = await oauth_store.get_client(kv, client_id)
    if client is None:
        return _html_error_page("invalid_client", "Unknown client_id. Please re-register the client.")
    if not redirect_uri or redirect_uri not in (client.get("redirect_uris") or []):
        return _html_error_page("invalid_redirect_uri", "redirect_uri does not match any registered URI.")
    if not _is_valid_redirect_uri(redirect_uri):
        return _html_error_page("invalid_redirect_uri", "redirect_uri scheme/host not allowed.")

    if response_type != "code":
        return _redirect_with_error(redirect_uri, state, "unsupported_response_type", "Only response_type=code is supported.")
    if code_challenge_method != "S256":
        return _redirect_with_error(redirect_uri, state, "invalid_request", "code_challenge_method must be S256.")
    if not code_challenge:
        return _redirect_with_error(redirect_uri, state, "invalid_request", "code_challenge is required (PKCE).")

    canonical = _canonical_resource(request)
    if resource_param and resource_param != canonical:
        return _redirect_with_error(redirect_uri, state, "invalid_target", f"resource must match {canonical}.")
    resource = resource_param or canonical
    scope = _normalize_scope(scope_param, client.get("scope", ""))

    sess = await auth.require_session(request, env)
    if sess is None:
        return_to = request.url
        return Response("", status=302, headers={
            "Location": f"/auth/login?return_to={urllib.parse.quote(return_to, safe='')}"
        })

    return _render_consent(
        client_name=client.get("client_name") or client_id,
        client_id=client_id, redirect_uri=redirect_uri, scope=scope,
        code_challenge=code_challenge, code_challenge_method=code_challenge_method,
        state=state, resource=resource, login=sess.get("login") or "", request_url=request.url,
    )


async def handle_authorize_grant(request, env) -> Response:
    kv = getattr(env, "AUTH_KV", None)
    if kv is None:
        return _html_error_page("server_error", "AUTH_KV not bound", status=500)

    sess = await auth.require_session(request, env)
    if sess is None:
        return Response("", status=302, headers={"Location": "/auth/login"})

    form = await _read_form_or_json(request)
    decision = form.get("decision", "")
    client_id = form.get("client_id", "")
    redirect_uri = form.get("redirect_uri", "")
    scope = form.get("scope", "")
    code_challenge = form.get("code_challenge", "")
    code_challenge_method = form.get("code_challenge_method", "")
    state = form.get("state", "")
    resource = form.get("resource", "")

    client = await oauth_store.get_client(kv, client_id)
    if client is None:
        return _html_error_page("invalid_client", "Unknown client_id.")
    if redirect_uri not in (client.get("redirect_uris") or []):
        return _html_error_page("invalid_redirect_uri", "redirect_uri does not match any registered URI.")
    if not _is_valid_redirect_uri(redirect_uri):
        return _html_error_page("invalid_redirect_uri", "redirect_uri scheme/host not allowed.")
    if code_challenge_method != "S256" or not code_challenge:
        return _redirect_with_error(redirect_uri, state, "invalid_request", "Missing or invalid PKCE challenge.")

    canonical = _canonical_resource(request)
    if resource and resource != canonical:
        return _redirect_with_error(redirect_uri, state, "invalid_target", f"resource must match {canonical}.")
    resource = resource or canonical

    if decision != "allow":
        return _redirect_with_error(redirect_uri, state, "access_denied", "User denied the authorization request.")

    user_sub = sess.get("user_sub", "")
    if not user_sub:
        return _redirect_with_error(redirect_uri, state, "server_error", "Session is missing user_sub.")

    code = await oauth_store.issue_authorization_code(
        kv, user_sub=user_sub, client_id=client_id, redirect_uri=redirect_uri,
        code_challenge=code_challenge, code_challenge_method=code_challenge_method,
        scope=scope or " ".join(SCOPES_SUPPORTED), resource=resource,
    )
    params = {"code": code}
    if state:
        params["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    return Response("", status=302, headers={"Location": f"{redirect_uri}{sep}{urllib.parse.urlencode(params)}"})


# --- Token endpoint --------------------------------------------------------


async def handle_token(request, env) -> Response:
    kv = getattr(env, "AUTH_KV", None)
    if kv is None:
        return _oauth_error("server_error", "AUTH_KV not bound", status=500)

    form = await _read_form_or_json(request)
    if form.get("grant_type", "") != "authorization_code":
        return _oauth_error("unsupported_grant_type", "Only grant_type=authorization_code is supported.")

    code = form.get("code", "")
    redirect_uri = form.get("redirect_uri", "")
    client_id = form.get("client_id", "")
    code_verifier = form.get("code_verifier", "")
    resource_param = form.get("resource", "")

    if not code or not client_id or not code_verifier or not redirect_uri:
        return _oauth_error("invalid_request", "code, client_id, redirect_uri, and code_verifier are required.")

    record = await oauth_store.consume_authorization_code(kv, code)
    if record is None:
        return _oauth_error("invalid_grant", "Authorization code is invalid or expired.")
    if record.get("client_id") != client_id:
        return _oauth_error("invalid_grant", "client_id does not match the authorization code.")
    if record.get("redirect_uri") != redirect_uri:
        return _oauth_error("invalid_grant", "redirect_uri does not match the authorization code.")
    if not _verify_pkce_s256(code_verifier, record.get("code_challenge", "")):
        return _oauth_error("invalid_grant", "PKCE code_verifier failed S256 check.")

    code_resource = record.get("resource") or _canonical_resource(request)
    if resource_param and resource_param != code_resource:
        return _oauth_error("invalid_target", "resource on token request must match the authorization code.")

    client = await oauth_store.get_client(kv, client_id)
    client_name = client.get("client_name") if client else None

    token = await oauth_store.issue_access_token(
        kv, user_sub=record["user_sub"], client_id=client_id,
        scope=record.get("scope", ""), client_name=client_name, resource=code_resource,
    )
    return _json_response({
        "access_token": token,
        "token_type": "Bearer",
        "scope": record.get("scope", ""),
    })
