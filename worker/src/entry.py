"""
gospelo-open-context Cloudflare Worker Entry Point

Remote MCP (Streamable HTTP) server that serves version-specific package
documentation and source code to coding agents. An rtfmbro/Context7
alternative implemented natively on Cloudflare Python Workers (GitHub API +
R2 content-addressed cache).

MCP endpoint:
    POST /mcp           MCP JSON-RPC over Streamable HTTP

Auth (added in Phase 1 — GitHub OAuth):
    GET  /auth/login | /auth/callback | /auth/logout
    GET  /.well-known/oauth-authorization-server[/mcp]
    GET  /.well-known/oauth-protected-resource[/mcp]
    POST /oauth/register | /oauth/token
    GET  /oauth/authorize     POST /oauth/authorize/grant
"""

import json

from workers import WorkerEntrypoint, Response

# Lazy imports for faster cold starts
_mcp_handler = None
_import_error = None


def _get_mcp():
    global _mcp_handler, _import_error
    if _mcp_handler is None and _import_error is None:
        try:
            import mcp_handler
            _mcp_handler = mcp_handler
        except Exception as e:
            import traceback
            _import_error = f"mcp_handler: {str(e)}\n{traceback.format_exc()}"
    return _mcp_handler


def cors_headers() -> dict:
    """CORS headers for cross-origin access."""
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization, Mcp-Session-Id, Accept, X-GitHub-Token, X-Debug-Github-Token",
        "Access-Control-Expose-Headers": "Mcp-Session-Id, WWW-Authenticate",
    }


def json_response(
    data: dict,
    status: int = 200,
    extra_headers: dict | None = None,
) -> Response:
    """JSON response helper."""
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        **cors_headers(),
    }
    if extra_headers:
        headers.update(extra_headers)
    return Response(
        json.dumps(data, ensure_ascii=False),
        status=status,
        headers=headers,
    )


def error_response(
    message: str,
    status: int = 400,
    extra_headers: dict | None = None,
) -> Response:
    """Error response helper."""
    return json_response({"success": False, "error": message}, status, extra_headers)


class Default(WorkerEntrypoint):
    """gospelo-open-context Worker Entrypoint"""

    async def fetch(self, request):
        try:
            url = request.url
            method = request.method

            # CORS preflight
            if method == "OPTIONS":
                return Response("", status=204, headers=cors_headers())

            # Parse path
            path = url.split("?")[0]
            if "://" in path:
                path = "/" + "/".join(path.split("/")[3:])
            path = path.rstrip("/")

            # --- Routes ---

            if (path == "" or path == "/") and method == "GET":
                return self._handle_root()

            if path == "/health":
                return json_response({"status": "ok"})

            # --- GitHub OAuth (browser login backing MCP consent) ---
            if path == "/auth/login" and method == "GET":
                import auth
                return await auth.handle_login(request, self.env)

            if path == "/auth/callback" and method == "GET":
                import auth
                return await auth.handle_callback(request, self.env)

            if path == "/auth/logout" and method in ("GET", "POST"):
                import auth
                return await auth.handle_logout(request, self.env)

            # --- OAuth 2.1 authorization server (MCP-client-facing) ---
            if path in (
                "/.well-known/oauth-authorization-server",
                "/.well-known/oauth-authorization-server/mcp",
            ) and method == "GET":
                import oauth_endpoints
                return await oauth_endpoints.handle_authorization_server_metadata(request, self.env)

            if path in (
                "/.well-known/oauth-protected-resource",
                "/.well-known/oauth-protected-resource/mcp",
            ) and method == "GET":
                import oauth_endpoints
                return await oauth_endpoints.handle_protected_resource_metadata(request, self.env)

            if path == "/oauth/register" and method == "POST":
                import oauth_endpoints
                return await oauth_endpoints.handle_register(request, self.env)

            if path == "/oauth/authorize" and method == "GET":
                import oauth_endpoints
                return await oauth_endpoints.handle_authorize(request, self.env)

            if path == "/oauth/authorize/grant" and method == "POST":
                import oauth_endpoints
                return await oauth_endpoints.handle_authorize_grant(request, self.env)

            if path == "/oauth/token" and method == "POST":
                import oauth_endpoints
                return await oauth_endpoints.handle_token(request, self.env)

            if path == "/mcp" or path == "/sse":
                mcp = _get_mcp()
                if mcp is None:
                    return error_response(f"MCP module error: {_import_error}", 500)
                # Forward all methods (GET, POST, DELETE, OPTIONS) to MCP handler
                return await mcp.handle_request(request, self.env)

            return error_response("Not Found", 404)

        except Exception as e:
            import traceback
            return error_response(
                f"Worker error: {str(e)}\n{traceback.format_exc()}", 500
            )

    def _handle_root(self) -> Response:
        """GET / - service information."""
        return json_response({
            "service": "gospelo-open-context",
            "version": getattr(self.env, "APP_VERSION", "0.0.0"),
            "commit": getattr(self.env, "DEPLOY_COMMIT", "unknown"),
            "description": (
                "Version-specific package docs + source for coding agents "
                "(rtfmbro/Context7 alternative)."
            ),
            "endpoints": {
                "GET /health": "Health check",
                "POST /mcp": "MCP JSON-RPC (Streamable HTTP)",
            },
            "mcp_tools": ["list_contexts", "get_readme", "get_documentation_tree", "read_files", "grep_repo", "get_outline"],
        })
