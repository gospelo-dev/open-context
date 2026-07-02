"""Shared auth resolution for the MCP entrypoint.

Two auth methods, both giving a per-user GitHub token (BYO — each user's own
account / rate limit / repo access):

1. BYO PAT (primary): the user supplies their own GitHub token via the
   `X-GitHub-Token` header, or `Authorization: Bearer <github-token>`. No OAuth
   App registration or server secrets required. The token is validated once via
   GET /user and cached (token-hash -> identity) in KV for an hour.
2. OAuth 2.1 (optional): our own issued Bearer token -> stored per-user GitHub
   token. Requires the GitHub OAuth App secrets to be configured.
"""

import hashlib
import json

SCOPES_SUPPORTED = ("mcp:read", "mcp:tools")
REALM = "gospelo-open-context"

# GitHub token prefixes (classic PAT, fine-grained PAT, OAuth/app tokens).
_GH_TOKEN_PREFIXES = ("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_")
_BYO_CACHE_TTL = 3600  # seconds to cache a validated PAT -> identity


def extract_origin(request) -> str:
    """Extract scheme + host from request URL."""
    url = request.url
    parts = url.split("/", 3)
    return "/".join(parts[:3]) if len(parts) >= 3 else url


def canonical_resource_uri(request) -> str:
    """Canonical MCP resource URI per RFC 8707 (includes /mcp path)."""
    return f"{extract_origin(request)}/mcp"


def www_authenticate_header(request) -> str:
    """RFC 9728 Bearer challenge pointing to protected-resource metadata."""
    metadata_url = f"{extract_origin(request)}/.well-known/oauth-protected-resource"
    scope = " ".join(SCOPES_SUPPORTED)
    return (
        f'Bearer realm="{REALM}", '
        f'resource_metadata="{metadata_url}", '
        f'scope="{scope}"'
    )


def _looks_like_github_token(tok: str) -> bool:
    return bool(tok) and tok.startswith(_GH_TOKEN_PREFIXES)


async def _resolve_byo_pat(env, token: str) -> dict | None:
    """Validate a user-supplied GitHub token (BYO PAT) and return auth context.

    Validated once via GET /user, then cached (token hash -> identity) in KV.
    """
    import github_client

    kv = getattr(env, "AUTH_KV", None)
    cache_key = "byotok:" + hashlib.sha256(token.encode()).hexdigest()[:20]

    if kv is not None:
        raw = await kv.get(cache_key)
        if raw:
            try:
                rec = json.loads(raw)
                return {"user_sub": rec["user_sub"], "login": rec.get("login", ""), "github_token": token}
            except (json.JSONDecodeError, TypeError, KeyError):
                pass

    r = await github_client.gh_get_json(token, "/user")
    if r["status"] != 200 or not r["json"]:
        return None
    user_sub = str(r["json"].get("id") or "")
    login = r["json"].get("login") or ""
    if not user_sub:
        return None

    if kv is not None:
        try:
            await kv.put(
                cache_key,
                json.dumps({"user_sub": user_sub, "login": login}),
                {"expirationTtl": _BYO_CACHE_TTL},
            )
        except Exception:
            pass

    return {"user_sub": user_sub, "login": login, "github_token": token}


async def resolve_auth_context(request, env) -> dict | None:
    """Resolve auth to {user_sub, login, github_token}, or None.

    Priority: X-GitHub-Token header, then Authorization: Bearer. A Bearer value
    that looks like a GitHub token is treated as a BYO PAT; otherwise it is
    looked up as an OAuth-issued token.
    """
    # 1. BYO PAT via dedicated header.
    pat = request.headers.get("X-GitHub-Token") or request.headers.get("x-github-token")
    if pat and pat.strip():
        return await _resolve_byo_pat(env, pat.strip())

    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None

    # 2. Bearer value that is itself a GitHub token -> BYO PAT.
    if _looks_like_github_token(token):
        return await _resolve_byo_pat(env, token)

    # 3. Otherwise treat as an OAuth-issued token (requires OAuth configured).
    kv = getattr(env, "AUTH_KV", None)
    if kv is None:
        return None

    import oauth_store
    import user_store

    record = await oauth_store.get_access_token(kv, token)
    if not record:
        return None
    user_sub = record.get("user_sub")
    if not user_sub:
        return None

    # RFC 8707 audience binding: reject tokens minted for a different resource.
    token_resource = record.get("resource")
    if token_resource and token_resource != canonical_resource_uri(request):
        return None

    github_token = await user_store.get_decrypted_github_token(env, kv, user_sub)
    if not github_token:
        return None

    try:
        await oauth_store.update_token_last_used(kv, token)
    except Exception:
        pass

    user = await user_store.get_user(kv, user_sub)
    login = (user or {}).get("login", "")
    return {"user_sub": user_sub, "login": login, "github_token": github_token}
