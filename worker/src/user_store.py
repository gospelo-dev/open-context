"""
CRUD for the `user:{user_sub}` records in AUTH_KV.

Schema:
    user:{user_sub} -> {
        "login": str,                        # GitHub login
        "encrypted_github_token": str|None,  # base64(iv || ciphertext || tag)
        "token_updated_at": str|None,        # ISO 8601 UTC
        "created_at": str,
        "updated_at": str,
    }

The GitHub OAuth access token IS the per-user credential — we use it to call
the GitHub API on that user's behalf (their own 5,000 req/h and repo access).
"""

import json
from datetime import datetime, timezone
from typing import Optional

import encryption


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _kv_key(user_sub: str) -> str:
    return f"user:{user_sub}"


async def get_user(kv, user_sub: str) -> Optional[dict]:
    raw = await kv.get(_kv_key(user_sub))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


async def save_github_token(env, kv, user_sub: str, login: str, plaintext_token: str) -> dict:
    """Encrypt and store the user's GitHub access token (create/refresh record)."""
    encrypted = await encryption.encrypt(env, plaintext_token)
    existing = await get_user(kv, user_sub) or {}
    now = _now_iso()
    record = {
        **existing,
        "login": login,
        "encrypted_github_token": encrypted,
        "token_updated_at": now,
        "updated_at": now,
    }
    record.setdefault("created_at", now)
    await kv.put(_kv_key(user_sub), json.dumps(record))
    return record


async def get_decrypted_github_token(env, kv, user_sub: str) -> Optional[str]:
    """Return the decrypted GitHub access token for a user, or None."""
    record = await get_user(kv, user_sub)
    if record is None:
        return None
    enc = record.get("encrypted_github_token")
    if not enc:
        return None
    return await encryption.decrypt(env, enc)
