"""
CRUD for the OAuth 2.1 records in AUTH_KV (MCP-client-facing authorization).

    oauth_client:{client_id}  -> client registration (RFC 7591)
    oauth_code:{code}         -> one-time PKCE authorization code (10 min TTL)
    access_token:{token}      -> Bearer token -> {user_sub, client_id, scope, ...}

`user_sub` is the GitHub user id (string). The per-user GitHub token itself is
stored encrypted under user:{user_sub} (see user_store.py); this module only
tracks the identity binding.

All tokens / codes / client_ids are 32-byte URL-safe random strings.
"""

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

AUTHORIZATION_CODE_TTL_SECONDS = 10 * 60  # RFC 6749 §4.1.2 short lifetime


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _client_key(client_id: str) -> str:
    return f"oauth_client:{client_id}"


def _code_key(code: str) -> str:
    return f"oauth_code:{code}"


def _token_key(token: str) -> str:
    return f"access_token:{token}"


# --- Clients (RFC 7591 Dynamic Client Registration) ------------------------


async def create_client(
    kv,
    redirect_uris: list,
    client_name: Optional[str] = None,
    scope: str = "mcp:read mcp:tools",
) -> dict:
    """Register a new public OAuth client (PKCE, no client secret)."""
    client_id = secrets.token_urlsafe(32)
    record = {
        "client_id": client_id,
        "client_name": client_name,
        "redirect_uris": list(redirect_uris),
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": scope,
        "created_at": _now_iso(),
    }
    await kv.put(_client_key(client_id), json.dumps(record))
    return record


async def get_client(kv, client_id: str) -> Optional[dict]:
    if not client_id:
        return None
    raw = await kv.get(_client_key(client_id))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


# --- Authorization codes (RFC 6749 §4.1 + RFC 7636 PKCE) -------------------


async def issue_authorization_code(
    kv,
    user_sub: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    scope: str,
    resource: Optional[str] = None,
) -> str:
    """Issue a one-time authorization code bound to a PKCE challenge."""
    code = secrets.token_urlsafe(32)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=AUTHORIZATION_CODE_TTL_SECONDS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {
        "code": code,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "user_sub": user_sub,
        "scope": scope,
        "resource": resource,
        "expires_at": expires_at,
    }
    await kv.put(
        _code_key(code),
        json.dumps(record),
        {"expirationTtl": AUTHORIZATION_CODE_TTL_SECONDS},
    )
    return code


async def consume_authorization_code(kv, code: str) -> Optional[dict]:
    """Look up an authorization code and delete it (one-time use)."""
    if not code:
        return None
    raw = await kv.get(_code_key(code))
    if raw is None:
        return None
    await kv.delete(_code_key(code))  # prevent replay
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


# --- Access tokens ---------------------------------------------------------


async def issue_access_token(
    kv,
    user_sub: str,
    client_id: str,
    scope: str,
    client_name: Optional[str] = None,
    resource: Optional[str] = None,
) -> str:
    """Issue a Bearer access token bound to (user_sub, client_id, resource)."""
    token = secrets.token_urlsafe(32)
    now = _now_iso()
    record = {
        "token": token,
        "client_id": client_id,
        "user_sub": user_sub,
        "scope": scope,
        "resource": resource,
        "client_name": client_name,
        "created_at": now,
        "last_used_at": now,
    }
    await kv.put(_token_key(token), json.dumps(record))
    return token


async def get_access_token(kv, token: str) -> Optional[dict]:
    if not token:
        return None
    raw = await kv.get(_token_key(token))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


async def update_token_last_used(kv, token: str) -> None:
    record = await get_access_token(kv, token)
    if record is None:
        return
    record["last_used_at"] = _now_iso()
    await kv.put(_token_key(token), json.dumps(record))


async def revoke_access_token(kv, token: str) -> None:
    if not token:
        return
    await kv.delete(_token_key(token))
