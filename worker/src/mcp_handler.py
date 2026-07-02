"""
MCP Streamable HTTP handler for gospelo-open-context.

Transport layer (JSON-RPC dispatch, SSE detection, CORS) is copied from the
proven chart-banana implementation. Tool set is specific to this server:
version-precise package docs + source fetched from GitHub.

Tools (MVP — npm ecosystem):
    get_readme(package, version, ecosystem)
    get_documentation_tree(package, version, ecosystem, scope?)
    read_files(package, version, ecosystem, requests[])
"""

import json
import re
from uuid import uuid4

try:  # pragma: no cover - real runtime is pyodide/workers
    from workers import Response
except ImportError:  # pragma: no cover - CPython unit tests
    Response = None

# Set per-request from Wrangler vars (see handle_request).
_server_version_tag = "gospelo-open-context"

SERVER_INFO = {
    "name": "gospelo-open-context",
    "version": "0.1.0",
}

CAPABILITIES = {
    "tools": {},
}

# ---------------------------------------------------------------------------
# Safety limits
# ---------------------------------------------------------------------------

MAX_FILE_SIZE = 1_000_000          # 1 MB per file (manifest build filters larger)
MAX_FILES_PER_READ = 20            # requests[] per read_files call
MAX_TOTAL_READ_BYTES = 2_000_000   # aggregate per read_files call
MAX_LINE_RANGE = 2000              # lines per slice
RESPONSE_TRUNCATE = 100_000        # bytes per text content block
MAX_TREE_TOOL_OUTPUT = 1500        # paths listed by get_documentation_tree

MAX_GREP_FILES = 400               # candidate files considered per grep
MAX_GREP_FETCH = 80                # uncached files fetched per grep (cost bound)
MAX_GREP_HITS = 100                # matching lines returned per grep
MAX_GREP_QUERY = 200               # max query length (ReDoS bound)
MAX_OUTLINE = 500                  # sections listed by get_outline


def _build_grep_matcher(query: str, regex: bool, ignore_case: bool):
    """Return (file_prefilter, line_match, error).

    file_prefilter(text)->bool cheaply skips non-matching files; line_match(
    line)->bool tests a single line. On a bad regex, error is a message and the
    two callables are None.
    """
    if len(query) > MAX_GREP_QUERY:
        return None, None, f"query too long (max {MAX_GREP_QUERY} chars)"
    if regex:
        try:
            pattern = re.compile(query, re.IGNORECASE if ignore_case else 0)
        except re.error as e:
            return None, None, f"invalid regex: {e}"
        return (lambda t: pattern.search(t) is not None), (lambda ln: pattern.search(ln) is not None), None
    needle = query.lower() if ignore_case else query

    def _pre(t):
        return needle in (t.lower() if ignore_case else t)

    def _line(ln):
        return needle in (ln.lower() if ignore_case else ln)

    return _pre, _line, None
_GREP_EXT = (
    ".md", ".mdx", ".rst", ".txt", ".markdown",
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json",
    ".py", ".pyi",
)
# Skip vendored/compiled/minified files — noise for symbol search.
_GREP_SKIP = ("dist/", "build/", "compiled/", "/vendor/", "node_modules/", ".min.")

_DOC_EXT = (".md", ".mdx", ".rst", ".txt", ".markdown")
_CONTENT_TYPES = {
    ".md": "text/markdown", ".mdx": "text/markdown", ".markdown": "text/markdown",
    ".rst": "text/x-rst", ".txt": "text/plain",
    ".ts": "text/plain", ".tsx": "text/plain", ".js": "text/plain",
    ".jsx": "text/plain", ".json": "application/json", ".py": "text/x-python",
    ".pyi": "text/x-python",
}

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

_COMMON_PROPS = {
    "package": {
        "type": "string",
        "description": (
            "Package name as published to the registry "
            "(e.g. 'next', 'react', '@scope/name')."
        ),
    },
    "version": {
        "type": "string",
        "description": (
            "Exact installed version. For npm read node_modules/{package}/"
            "package.json 'version' (or the lockfile); for pypi read the "
            "installed dist-info / lockfile (uv.lock, poetry.lock, "
            "requirements.txt). NOT a semver range. Example: '15.1.0'."
        ),
    },
    "ecosystem": {
        "type": "string",
        "description": "Package registry ecosystem.",
        "enum": ["npm", "pypi"],
        "default": "npm",
    },
}

TOOLS = [
    {
        "name": "get_readme",
        "description": (
            "Fetch the README for an exact package version, straight from the "
            "matching git tag on GitHub. Start here to understand a library at "
            "the version the project actually uses. For deeper detail use "
            "get_documentation_tree then read_files."
        ),
        "inputSchema": {
            "type": "object",
            "properties": dict(_COMMON_PROPS),
            "required": ["package", "version"],
        },
    },
    {
        "name": "get_documentation_tree",
        "description": (
            "List the documentation and (optionally) source file paths for an "
            "exact package version, with sizes. Use this to locate the right "
            "files before calling read_files. scope='docs' returns doc files "
            "only (.md/.mdx/.rst/.txt); scope='all' returns the full tree "
            "including source, type definitions, examples and tests."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_COMMON_PROPS,
                "scope": {
                    "type": "string",
                    "description": "Which files to list.",
                    "enum": ["docs", "all"],
                    "default": "docs",
                },
            },
            "required": ["package", "version"],
        },
    },
    {
        "name": "read_files",
        "description": (
            "Read specific files at an exact package version. Not limited to "
            "docs — read source (.ts/.js/.py), type definitions (.d.ts/.pyi), "
            "examples/ and tests to get exact signatures and real usage. "
            "Optionally slice by line range. Paths come from "
            "get_documentation_tree."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_COMMON_PROPS,
                "requests": {
                    "type": "array",
                    "description": "Files to read (max 20 per call).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": (
                                    "Path relative to the package subdir (as shown by "
                                    "get_documentation_tree). A leading '/' means a "
                                    "repo-root path (repo-root docs listed with '/')."
                                ),
                            },
                            "start_line": {
                                "type": "integer",
                                "description": "1-indexed first line (optional).",
                            },
                            "end_line": {
                                "type": "integer",
                                "description": "1-indexed last line, inclusive (optional).",
                            },
                        },
                        "required": ["path"],
                    },
                },
            },
            "required": ["package", "version", "requests"],
        },
    },
    {
        "name": "grep_repo",
        "description": (
            "Search within an exact package version for a literal string "
            "(e.g. a symbol, function, option or config key) and return the "
            "matching file paths + line numbers. Use this to locate where "
            "something is defined or used before read_files, when you don't "
            "know the path. Skips vendored/compiled files. Coverage is bounded "
            "per call — the response reports how many files were scanned."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_COMMON_PROPS,
                "query": {
                    "type": "string",
                    "description": "Search string. Literal substring by default; a Python regex when regex=true.",
                },
                "ignore_case": {
                    "type": "boolean",
                    "description": "Case-insensitive match (default false).",
                    "default": False,
                },
                "regex": {
                    "type": "boolean",
                    "description": (
                        "Treat query as a Python regular expression (default false). "
                        "Use for flexible matching, e.g. 'use[_ ]?router'."
                    ),
                    "default": False,
                },
            },
            "required": ["package", "version", "query"],
        },
    },
    {
        "name": "get_outline",
        "description": (
            "Return the structural outline of a single file at an exact version "
            "— Markdown headings or top-level code symbols (function/class/type/"
            "def) — each with a line range. Use this to find the relevant "
            "section cheaply, then read ONLY that range with read_files instead "
            "of the whole file (token-efficient)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_COMMON_PROPS,
                "path": {
                    "type": "string",
                    "description": "File path (subdir-relative, or '/'-prefixed for repo-root docs).",
                },
            },
            "required": ["package", "version", "path"],
        },
    },
    {
        "name": "list_contexts",
        "description": (
            "List what this server supports: the package ecosystems and the "
            "libraries with curated documentation overrides (docs sourced from "
            "a separate repo). IMPORTANT: any npm/PyPI package that resolves to "
            "a public GitHub repo works — the override list is only the "
            "special-cased ones, not the full set of usable packages. Takes no "
            "arguments."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
]

# ---------------------------------------------------------------------------
# Transport helpers (copied from chart-banana mcp_handler.py)
# ---------------------------------------------------------------------------


def _cors_headers() -> dict:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization, Mcp-Session-Id, Accept, X-GitHub-Token, X-Debug-Github-Token",
        "Access-Control-Expose-Headers": "Mcp-Session-Id, WWW-Authenticate",
    }


def _jsonrpc_response(msg_id, result: dict) -> dict:
    if "content" in result and isinstance(result["content"], list):
        result["content"].append({
            "type": "text",
            "text": f"server: {_server_version_tag}",
        })
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _jsonrpc_error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _sse_event(data: dict, event_id: str = None) -> str:
    """Format a single SSE event."""
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


def _json_resp(data: dict, status: int = 200, extra_headers: dict = None) -> Response:
    headers = {
        "Content-Type": "application/json",
        **_cors_headers(),
    }
    if extra_headers:
        headers.update(extra_headers)
    return Response(
        json.dumps(data, ensure_ascii=False),
        status=status,
        headers=headers,
    )


def _sse_resp(data: dict, extra_headers: dict = None) -> Response:
    """Return a single JSON-RPC response wrapped in SSE format."""
    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        **_cors_headers(),
    }
    if extra_headers:
        headers.update(extra_headers)
    body = _sse_event(data, event_id=str(uuid4()))
    return Response(body, status=200, headers=headers)


def _accepted_resp(extra_headers: dict = None) -> Response:
    """Return 202 Accepted for notifications/responses."""
    headers = _cors_headers()
    if extra_headers:
        headers.update(extra_headers)
    return Response("", status=202, headers=headers)


def _wants_sse(request) -> bool:
    """Check if client prefers SSE (text/event-stream) over JSON."""
    accept = request.headers.get("Accept") or request.headers.get("accept") or ""
    return "text/event-stream" in accept


def _make_response(data: dict, request, extra_headers: dict = None) -> Response:
    """Return JSON-RPC response in the format the client prefers (SSE or JSON)."""
    if _wants_sse(request):
        return _sse_resp(data, extra_headers)
    return _json_resp(data, extra_headers=extra_headers)


def _text_result(text: str, is_error: bool = False) -> dict:
    result = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["isError"] = True
    return result


# ---------------------------------------------------------------------------
# Request dispatch
# ---------------------------------------------------------------------------


async def handle_request(request, env) -> Response:
    """Handle MCP Streamable HTTP transport requests."""
    method = request.method

    if method == "OPTIONS":
        return Response("", status=204, headers=_cors_headers())

    if method == "GET":
        return Response(
            ": keepalive\n\n",
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                **_cors_headers(),
            },
        )

    if method == "DELETE":
        return _accepted_resp()

    if method != "POST":
        return Response("Method not allowed", status=405, headers=_cors_headers())

    # Set version tag from Wrangler vars (available on every request via env)
    global _server_version_tag
    app_ver = getattr(env, "APP_VERSION", "0.0.0")
    deploy_commit = getattr(env, "DEPLOY_COMMIT", "unknown")
    _server_version_tag = f"gospelo-open-context v{app_ver} ({deploy_commit})"

    # Parse JSON-RPC request
    try:
        body_text = await request.text()
        message = json.loads(body_text)
    except Exception as e:
        return _json_resp(_jsonrpc_error(None, -32700, f"Parse error: {str(e)}"))

    if isinstance(message, list):
        if not message:
            return _accepted_resp()
        message = message[0]

    jsonrpc_method = message.get("method")
    msg_id = message.get("id")
    params = message.get("params", {})

    if msg_id is None or jsonrpc_method in ("notifications/initialized", "notifications/cancelled"):
        return _accepted_resp()

    # MCP Authorization gate. Unauthenticated requests to the protected
    # resource get 401 + WWW-Authenticate so clients start the GitHub OAuth
    # flow. Gated for ALL methods (incl. initialize) because clients like Codex
    # probe initialize first and conclude "Auth: Unsupported" if it succeeds
    # without a challenge. In development, an X-Debug-Github-Token header (or
    # even no token) is accepted so the handshake can be exercised locally.
    auth_ctx = await _resolve_auth(request, env)
    if auth_ctx is None:
        return _www_authenticate_401(request, msg_id=msg_id)

    if jsonrpc_method == "initialize":
        session_id = str(uuid4())
        result = {
            "protocolVersion": "2025-03-26",
            "serverInfo": SERVER_INFO,
            "capabilities": CAPABILITIES,
        }
        resp_data = _jsonrpc_response(msg_id, result)
        return _make_response(resp_data, request, extra_headers={"Mcp-Session-Id": session_id})

    if jsonrpc_method == "ping":
        return _make_response(_jsonrpc_response(msg_id, {}), request)

    if jsonrpc_method == "tools/list":
        return _make_response(_jsonrpc_response(msg_id, {"tools": TOOLS}), request)

    if jsonrpc_method == "tools/call":
        return await _handle_tool_call(msg_id, params, env, request, auth_ctx)

    return _make_response(
        _jsonrpc_error(msg_id, -32601, f"Method not found: {jsonrpc_method}"),
        request,
    )


def _dev_mode(env) -> bool:
    return getattr(env, "ENVIRONMENT", "") == "development"


async def _resolve_auth(request, env) -> dict | None:
    """Resolve the request's auth context, or None to trigger a 401 challenge.

    Development: always returns a context (never blocks), honoring an optional
    X-Debug-Github-Token so tools can run without the OAuth flow. Production:
    requires a valid GitHub-OAuth Bearer token (auth_resolver)."""
    if _dev_mode(env):
        t = request.headers.get("X-Debug-Github-Token") or request.headers.get("x-debug-github-token")
        return {"user_sub": "dev", "login": "dev", "github_token": t}
    import auth_resolver
    return await auth_resolver.resolve_auth_context(request, env)


def _www_authenticate_401(request, msg_id=None) -> Response:
    """401 with RFC 9728 WWW-Authenticate so MCP clients start GitHub OAuth."""
    import auth_resolver
    error_text = (
        "Authentication required. Provide your own GitHub token (BYO): add an "
        "'X-GitHub-Token: <your GitHub token>' header (or 'Authorization: Bearer "
        "<your GitHub token>') to the MCP server config. A classic PAT with no "
        "scopes reads public repos at your own 5,000 req/h; add 'repo' scope for "
        "private repos. (If the GitHub OAuth App is configured, a browser sign-in "
        "flow is also available.)"
    )
    headers = {
        "Content-Type": "application/json",
        "WWW-Authenticate": auth_resolver.www_authenticate_header(request),
        **_cors_headers(),
    }
    body = {"jsonrpc": "2.0", "error": {"code": -32001, "message": error_text}, "id": msg_id}
    return Response(json.dumps(body, ensure_ascii=False), status=401, headers=headers)


def _ext(path: str) -> str:
    i = path.rfind(".")
    return path[i:].lower() if i >= 0 else ""


def _content_type(path: str) -> str:
    return _CONTENT_TYPES.get(_ext(path), "text/plain")


def _is_doc_path(path: str) -> bool:
    return path.lower().endswith(_DOC_EXT)


def _is_root_doc(path: str) -> bool:
    """Prose docs living at the repo root (outside the package subdir).

    Captures the top-level docs/ tree and top-level doc files (README, guides,
    llms.txt / llms-full.txt) — the docs many frameworks keep outside their
    published package directory (e.g. next.js docs/).
    """
    low = path.lower()
    if path.startswith("docs/"):
        return low.endswith(_DOC_EXT)
    if "/" not in path:
        return low.endswith(_DOC_EXT) or low in ("llms.txt", "llms-full.txt")
    return False


def _resolve_entry(manifest: dict, path: str):
    """Resolve a tool path to (info, full_repo_path).

    Convention: a leading '/' means a repo-root path (from root_docs); anything
    else is relative to the package subdir (from files).
    """
    subdir = manifest.get("subdir") or ""
    if path.startswith("/"):
        rp = path[1:]
        return manifest.get("root_docs", {}).get(rp), rp
    info = manifest["files"].get(path)
    full = f"{subdir}/{path}" if subdir else path
    return info, full


def _pin_header(pin: dict) -> str:
    loc = f"{pin['owner']}/{pin['repo']}"
    if pin.get("subdir"):
        loc += f"/{pin['subdir']}"
    line = f"{pin['package']}@{pin['version']} — {loc} @ {pin['tag']} ({pin['commit_sha'][:7]})"
    if pin.get("warning"):
        line += f"\n⚠️ {pin['warning']}"
    return line


async def _get_or_build_manifest(r2, token, pin: dict) -> dict:
    import cache_store
    import github_client

    eco, pkg, ver = pin["ecosystem"], pin["package"], pin["version"]
    m = await cache_store.get_manifest(r2, eco, pkg, ver)
    if m:
        return m

    tree = await github_client.get_tree(token, pin["owner"], pin["repo"], pin["commit_sha"])
    subdir = pin.get("subdir") or ""
    prefix = (subdir + "/") if subdir else ""
    files = {}
    root_docs = {}
    for e in tree["entries"]:
        if e.get("type") != "blob":
            continue
        p = e.get("path", "")
        size = e.get("size", 0)
        if size > MAX_FILE_SIZE:
            continue
        if prefix:
            if p.startswith(prefix):
                rel = p[len(prefix):]
                if rel:
                    files[rel] = {"sha": e.get("sha"), "size": size}
            elif _is_root_doc(p):
                # Prose docs / llms.txt that live at the repo root, outside the
                # package subdir (e.g. next.js docs/, React-style top-level docs).
                root_docs[p] = {"sha": e.get("sha"), "size": size}
        else:
            files[p] = {"sha": e.get("sha"), "size": size}

    m = {
        "commit_sha": pin["commit_sha"],
        "tree_etag": tree.get("etag"),
        "generated_at": _now(),
        "owner": pin["owner"],
        "repo": pin["repo"],
        "subdir": subdir,
        "partial": tree.get("truncated", False),
        "files": files,
        "root_docs": root_docs,
    }
    await cache_store.put_manifest(r2, eco, pkg, ver, m)
    return m


def _now() -> int:
    import time
    return int(time.time())


async def _get_or_build_docs_manifest(r2, token, docs_pin: dict) -> dict:
    """Self-contained manifest for a docs-override repo (content-addressed by
    commit). Holds only doc files under the override subdir."""
    import cache_store
    import github_client

    owner, repo, csha = docs_pin["owner"], docs_pin["repo"], docs_pin["commit_sha"]
    m = await cache_store.get_docs_manifest(r2, owner, repo, csha)
    if m:
        return m

    tree = await github_client.get_tree(token, owner, repo, csha)
    subdir = docs_pin.get("subdir") or ""
    prefix = (subdir + "/") if subdir else ""
    files = {}
    for e in tree["entries"]:
        if e.get("type") != "blob":
            continue
        p = e.get("path", "")
        size = e.get("size", 0)
        if size > MAX_FILE_SIZE:
            continue
        if prefix and not p.startswith(prefix):
            continue
        rel = p[len(prefix):] if prefix else p
        if not rel or not _is_doc_path(rel):
            continue
        files[rel] = {"sha": e.get("sha"), "size": size}

    m = {
        "commit_sha": csha, "tree_etag": tree.get("etag"), "generated_at": _now(),
        "owner": owner, "repo": repo, "subdir": subdir, "ref": docs_pin.get("ref"),
        "partial": tree.get("truncated", False), "files": files, "root_docs": {},
        "is_docs": True,
    }
    await cache_store.put_docs_manifest(r2, owner, repo, csha, m)
    return m


async def _read_across(r2, token, manifests, path: str):
    """Read `path` from the first manifest that contains it (code, then docs)."""
    for m in manifests:
        info, _full = _resolve_entry(m, path)
        if info:
            return await _read_file(r2, token, m, path)
    return None, f"not found: {path}"


async def _manifests_for(r2, token, pin: dict) -> list:
    """Manifests to search for a package: code repo, plus docs-override repo."""
    manifests = [await _get_or_build_manifest(r2, token, pin)]
    if pin.get("docs_pin"):
        manifests.append(await _get_or_build_docs_manifest(r2, token, pin["docs_pin"]))
    return manifests


async def _load_bytes(r2, token, manifest, path: str):
    """Return (data|None, was_fetched, note). Uses the manifest's own repo
    location (owner/repo/commit_sha), so docs manifests from a different repo
    work transparently. R2 cache first, then GitHub."""
    import cache_store
    import github_client

    info, full = _resolve_entry(manifest, path)
    if not info:
        return None, False, f"not found: {path}"
    sha = info["sha"]
    data = await cache_store.get_blob(r2, sha)
    if data is not None:
        return data, False, None
    owner, repo = manifest["owner"], manifest["repo"]
    data = await github_client.get_raw_file(token, owner, repo, manifest["commit_sha"], full)
    if data is None:
        data = await github_client.get_blob(token, owner, repo, sha)
    if data is None:
        return None, True, f"fetch failed: {path}"
    await cache_store.put_blob(r2, sha, data, _content_type(path))
    return data, True, None


async def _read_file(r2, token, manifest, path: str):
    """Return (text, note). text is None on failure/binary with note set."""
    data, _fetched, note = await _load_bytes(r2, token, manifest, path)
    if data is None:
        return None, note or f"unavailable: {path}"
    if b"\x00" in data[:8000]:
        return None, f"binary file skipped: {path}"
    try:
        return data.decode("utf-8"), None
    except Exception:
        return None, f"non-UTF-8 file skipped: {path}"


def _grep_candidate(path: str) -> bool:
    low = path.lower()
    if not low.endswith(_GREP_EXT):
        return False
    return not any(marker in low for marker in _GREP_SKIP)


def _slice_lines(text: str, start: int | None, end: int | None) -> str:
    if not start and not end:
        return text
    lines = text.split("\n")
    s = max((start or 1), 1)
    e = end or (s + MAX_LINE_RANGE - 1)
    e = min(e, s + MAX_LINE_RANGE - 1, len(lines))
    return "\n".join(lines[s - 1:e])


def _truncate(text: str) -> str:
    if len(text) <= RESPONSE_TRUNCATE:
        return text
    return text[:RESPONSE_TRUNCATE] + f"\n\n...[truncated {len(text) - RESPONSE_TRUNCATE} bytes]"


def _pick_readme(files: dict) -> str | None:
    candidates = [p for p in files if p.rsplit("/", 1)[-1].lower().startswith("readme")]
    if not candidates:
        return None
    # Prefer a root README, then shortest path, .md first.
    candidates.sort(key=lambda p: (p.count("/"), 0 if p.lower().endswith(".md") else 1, len(p)))
    return candidates[0]


def _contexts_text() -> str:
    """Human/agent-readable listing of supported ecosystems + curated overrides."""
    import overrides

    lines = ["gospelo-open-context — supported contexts", ""]
    lines.append("Ecosystems: " + ", ".join(sorted(overrides.ECOSYSTEMS.keys())))
    lines.append(
        "Any package in these ecosystems that resolves to a public GitHub repo "
        "works — call a tool with {package, version, ecosystem}. The list below "
        "is ONLY the libraries with curated docs overrides (docs served from a "
        "separate repo); it is not the full set of usable packages."
    )
    lines.append("")
    lines.append("Curated docs overrides:")
    for key in sorted(overrides.OVERRIDES):
        d = (overrides.OVERRIDES[key] or {}).get("docs")
        if d:
            sub = f" ({d['subdir']})" if d.get("subdir") else ""
            lines.append(f"  {key} → docs: {d['repo']}@{d.get('ref')}{sub}")
    return "\n".join(lines)


async def _handle_tool_call(msg_id, params: dict, env, request, auth_ctx: dict) -> Response:
    """Execute an MCP tool call."""
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    # Discovery tool — no package/version/token needed.
    if tool_name == "list_contexts":
        return _make_response(_jsonrpc_response(msg_id, _text_result(_contexts_text())), request)

    handlers = {
        "get_readme": _tool_get_readme,
        "get_documentation_tree": _tool_get_documentation_tree,
        "read_files": _tool_read_files,
        "grep_repo": _tool_grep_repo,
        "get_outline": _tool_get_outline,
    }
    handler = handlers.get(tool_name)
    if handler is None:
        return _make_response(
            _jsonrpc_error(msg_id, -32602, f"Unknown tool: {tool_name}"), request
        )

    import version_resolver

    token = (auth_ctx or {}).get("github_token")
    r2 = getattr(env, "CACHE", None)
    pkg = arguments.get("package")
    ver = arguments.get("version")
    eco = arguments.get("ecosystem", "npm")
    if not pkg or not ver:
        return _make_response(
            _jsonrpc_response(msg_id, _text_result("Error: 'package' and 'version' are required.", True)),
            request,
        )

    try:
        pin = await version_resolver.resolve(env, token, pkg, ver, eco)
    except version_resolver.ResolveError as e:
        return _make_response(
            _jsonrpc_response(msg_id, _text_result(f"Resolution failed: {e}", True)), request
        )
    except Exception as e:
        import traceback
        return _make_response(
            _jsonrpc_response(msg_id, _text_result(f"Unexpected error: {e}\n{traceback.format_exc()}", True)),
            request,
        )

    return await handler(msg_id, arguments, env, request, r2, token, pin)


async def _tool_get_readme(msg_id, args, env, request, r2, token, pin) -> Response:
    manifest = await _get_or_build_manifest(r2, token, pin)
    readme = _pick_readme(manifest["files"])
    if not readme:
        # Fall back to a repo-root README (package subdir had none).
        root_readme = _pick_readme(manifest.get("root_docs", {}))
        if root_readme:
            readme = "/" + root_readme
    if not readme:
        return _make_response(
            _jsonrpc_response(msg_id, _text_result(
                f"{_pin_header(pin)}\n\nNo README found in this package.", True)),
            request,
        )
    text, note = await _read_file(r2, token, manifest, readme)
    if text is None:
        return _make_response(
            _jsonrpc_response(msg_id, _text_result(f"{_pin_header(pin)}\n\nError: {note}", True)), request
        )
    body = f"{_pin_header(pin)}\n\n--- {readme} ---\n\n{_truncate(text)}"
    return _make_response(_jsonrpc_response(msg_id, _text_result(body)), request)


async def _tool_get_documentation_tree(msg_id, args, env, request, r2, token, pin) -> Response:
    scope = args.get("scope", "docs")
    docs_pin = pin.get("docs_pin")

    # Curated docs override: for scope=docs, the authoritative docs live in a
    # separate (usually unversioned) repo. read_files can fetch these paths too.
    if scope == "docs" and docs_pin:
        dm = await _get_or_build_docs_manifest(r2, token, docs_pin)
        entries = sorted(dm["files"].items())
        shown = entries[:MAX_TREE_TOOL_OUTPUT]
        lines = [f"{p}  ({info['size']} B)" for p, info in shown]
        src = f"{docs_pin['owner']}/{docs_pin['repo']}@{docs_pin.get('ref')}"
        header = (
            f"{_pin_header(pin)}\n\n{len(entries)} docs files from {src} "
            f"(⚠️ docs repo is unversioned — content reflects latest, not {pin['version']})"
        )
        if len(entries) > len(shown):
            header += f" (showing first {len(shown)})"
        body = header + ":\n\n" + "\n".join(lines)
        return _make_response(_jsonrpc_response(msg_id, _text_result(body)), request)

    manifest = await _get_or_build_manifest(r2, token, pin)
    files = manifest["files"]
    root_docs = manifest.get("root_docs", {})

    entries = []  # (display_path, size)
    for p, info in files.items():
        if scope == "docs" and not _is_doc_path(p):
            continue
        entries.append((p, info["size"]))
    # Repo-root docs (outside the package subdir) are shown with a leading '/'.
    for rp, info in root_docs.items():
        entries.append(("/" + rp, info["size"]))
    entries.sort(key=lambda t: t[0])

    shown = entries[:MAX_TREE_TOOL_OUTPUT]
    lines = [f"{p}  ({size} B)" for p, size in shown]
    header = f"{_pin_header(pin)}\n\n{len(entries)} {scope} files"
    if len(entries) > len(shown):
        header += f" (showing first {len(shown)})"
    if root_docs:
        header += f"  [{len(root_docs)} repo-root doc file(s) shown with a leading '/'; pass that exact path to read_files]"
    if manifest.get("partial"):
        header += "  ⚠️ tree truncated by GitHub (very large repo)"
    body = header + ":\n\n" + "\n".join(lines)
    return _make_response(_jsonrpc_response(msg_id, _text_result(body)), request)


async def _tool_read_files(msg_id, args, env, request, r2, token, pin) -> Response:
    requests = args.get("requests") or []
    if not isinstance(requests, list) or not requests:
        return _make_response(
            _jsonrpc_response(msg_id, _text_result("Error: 'requests' must be a non-empty array.", True)),
            request,
        )
    if len(requests) > MAX_FILES_PER_READ:
        return _make_response(
            _jsonrpc_response(msg_id, _text_result(
                f"Error: too many files ({len(requests)}); max {MAX_FILES_PER_READ} per call.", True)),
            request,
        )
    manifests = await _manifests_for(r2, token, pin)
    blocks = [f"{_pin_header(pin)}"]
    total = 0
    for req in requests:
        path = (req or {}).get("path")
        if not path:
            blocks.append("--- (missing path) ---\nError: 'path' required")
            continue
        text, note = await _read_across(r2, token, manifests, path)
        if text is None:
            blocks.append(f"--- {path} ---\nError: {note}")
            continue
        sliced = _slice_lines(text, req.get("start_line"), req.get("end_line"))
        if total + len(sliced) > MAX_TOTAL_READ_BYTES:
            remaining = MAX_TOTAL_READ_BYTES - total
            sliced = sliced[:max(remaining, 0)] + "\n...[read budget exhausted]"
            blocks.append(f"--- {path} ---\n{sliced}")
            break
        total += len(sliced)
        blocks.append(f"--- {path} ---\n{_truncate(sliced)}")
    return _make_response(_jsonrpc_response(msg_id, _text_result("\n\n".join(blocks))), request)


async def _tool_grep_repo(msg_id, args, env, request, r2, token, pin) -> Response:
    query = args.get("query")
    if not query or not isinstance(query, str):
        return _make_response(
            _jsonrpc_response(msg_id, _text_result("Error: 'query' is required.", True)), request
        )
    ignore_case = bool(args.get("ignore_case"))
    regex = bool(args.get("regex"))
    file_prefilter, line_match, err = _build_grep_matcher(query, regex, ignore_case)
    if err:
        return _make_response(_jsonrpc_response(msg_id, _text_result(f"Error: {err}", True)), request)

    manifests = await _manifests_for(r2, token, pin)
    candidates = []  # (manifest, path)
    for m in manifests:
        candidates += [(m, p) for p in m["files"] if _grep_candidate(p)]
        candidates += [(m, "/" + rp) for rp in m.get("root_docs", {}) if _grep_candidate(rp)]
    candidates.sort(key=lambda t: t[1])
    considered = len(candidates)
    candidates = candidates[:MAX_GREP_FILES]

    hits: list[tuple] = []
    scanned = 0
    fetched = 0
    hit_cap = False
    for manifest, path in candidates:
        if len(hits) >= MAX_GREP_HITS:
            hit_cap = True
            break
        data, was_fetched, _note = await _load_bytes(r2, token, manifest, path)
        if was_fetched:
            fetched += 1
        if data is None or b"\x00" in data[:8000]:
            # Respect the fetch budget: stop pulling new uncached files once hit.
            if was_fetched and fetched >= MAX_GREP_FETCH:
                break
            continue
        try:
            text = data.decode("utf-8")
        except Exception:
            continue
        scanned += 1
        if not file_prefilter(text):
            if was_fetched and fetched >= MAX_GREP_FETCH:
                break
            continue
        for i, line in enumerate(text.split("\n"), 1):
            if line_match(line):
                hits.append((path, i, line.strip()[:200]))
                if len(hits) >= MAX_GREP_HITS:
                    hit_cap = True
                    break
        if was_fetched and fetched >= MAX_GREP_FETCH:
            break

    lines = [f"{p}:{ln}: {txt}" for p, ln, txt in hits]
    header = f"{_pin_header(pin)}\n\n"
    flags = ("regex" if regex else "literal") + (", i" if ignore_case else "")
    header += f"grep '{query}' ({flags}): {len(hits)} hit(s) in {scanned} scanned file(s)"
    notes = []
    if considered > len(candidates):
        notes.append(f"{considered} candidate files, capped scan at {len(candidates)}")
    if fetched >= MAX_GREP_FETCH:
        notes.append(f"fetch budget {MAX_GREP_FETCH} reached — re-run to scan more (fetched files are now cached)")
    if hit_cap:
        notes.append(f"hit cap {MAX_GREP_HITS} reached")
    if notes:
        header += "  [" + "; ".join(notes) + "]"
    body = header + ("\n\n" + "\n".join(lines) if lines else "\n\n(no matches)")
    return _make_response(_jsonrpc_response(msg_id, _text_result(body)), request)


async def _tool_get_outline(msg_id, args, env, request, r2, token, pin) -> Response:
    path = args.get("path")
    if not path or not isinstance(path, str):
        return _make_response(
            _jsonrpc_response(msg_id, _text_result("Error: 'path' is required.", True)), request
        )
    manifests = await _manifests_for(r2, token, pin)
    text, note = await _read_across(r2, token, manifests, path)
    if text is None:
        return _make_response(
            _jsonrpc_response(msg_id, _text_result(f"{_pin_header(pin)}\n\nError: {note}", True)), request
        )

    import chunker
    sections = chunker.outline(text, path)
    total_lines = text.count("\n") + 1
    header = f"{_pin_header(pin)}\n\n{path} — "
    if not sections:
        body = (
            header + f"no structural outline detected ({total_lines} lines). "
            "Read it directly with read_files."
        )
        return _make_response(_jsonrpc_response(msg_id, _text_result(body)), request)

    shown = sections[:MAX_OUTLINE]
    lines = []
    for s in shown:
        if s["kind"] == "heading" and s["level"] > 0:
            label = "  " * (s["level"] - 1) + s["title"]
        elif s["kind"] in ("heading", "preamble"):
            label = s["title"]
        else:
            label = f"{s['kind']} {s['title']}"
        lines.append(f"L{s['start_line']}-{s['end_line']}  {label}")
    header += f"{len(sections)} sections ({total_lines} lines)"
    if len(sections) > len(shown):
        header += f" (showing first {len(shown)})"
    body = (
        header + ":\n\n" + "\n".join(lines)
        + "\n\nRead a section with read_files using its start_line/end_line."
    )
    return _make_response(_jsonrpc_response(msg_id, _text_result(body)), request)
