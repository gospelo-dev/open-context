"""Shared auth resolution for the MCP entrypoint (GitHub OAuth Bearer tokens)."""

SCOPES_SUPPORTED = ("mcp:read", "mcp:tools")
REALM = "gospelo-open-context"


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


async def resolve_auth_context(request, env) -> dict | None:
    """Resolve a Bearer token to an auth context, or None.

    Returns: {user_sub, login, github_token} — github_token is the per-user
    GitHub OAuth token used for all downstream GitHub API calls.
    """
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    kv = getattr(env, "AUTH_KV", None)
    if kv is None or not token:
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
