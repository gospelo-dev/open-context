"""
GitHub API client for gospelo-open-context (Cloudflare Python Worker / pyodide).

Outbound HTTP uses js.fetch + to_js marshalling (see chart-banana
gemini_client.py). The caller supplies the GitHub token — in production it is
the per-user OAuth token (from auth_ctx); in dev it may be a debug token or
None (unauthenticated, 60 req/h).

Version-precise fetching avoids `git clone`: we read the recursive git tree
(one call → every {path,size,sha}) and fetch individual file contents by
commit SHA (raw, no core-rate cost) or by blob SHA (Blobs API).

js imports are guarded so the pure helpers remain importable under CPython
for unit tests; the async network functions require the pyodide runtime.
"""

import json
import re
import urllib.parse
from base64 import b64decode

try:  # pragma: no cover - real runtime is pyodide
    from js import fetch as js_fetch, Object, Uint8Array
    from pyodide.ffi import to_js
except ImportError:  # pragma: no cover - CPython unit tests
    js_fetch = None
    Object = None
    Uint8Array = None

    def to_js(obj, **_):
        return obj


GH_API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
_UA = "gospelo-open-context"


def _headers(token, accept="application/vnd.github+json") -> dict:
    h = {
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": _UA,
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def _fetch(url: str, headers: dict, method: str = "GET"):
    options = to_js(
        {"method": method, "headers": headers},
        dict_converter=Object.fromEntries,
    )
    return await js_fetch(url, options)


async def gh_get_json(token, path: str, etag: str | None = None) -> dict:
    """GET an api.github.com path. Returns a normalized envelope.

    Envelope: {status, ok, not_modified, etag, rate_remaining, rate_reset,
               json, text}
    """
    headers = _headers(token)
    if etag:
        headers["If-None-Match"] = etag
    resp = await _fetch(GH_API + path, headers)
    out = {
        "status": resp.status,
        "ok": bool(resp.ok),
        "not_modified": resp.status == 304,
        "etag": resp.headers.get("etag"),
        "rate_remaining": resp.headers.get("x-ratelimit-remaining"),
        "rate_reset": resp.headers.get("x-ratelimit-reset"),
        "json": None,
        "text": None,
    }
    if resp.status == 304:
        return out
    text = await resp.text()
    out["text"] = text
    try:
        out["json"] = json.loads(text)
    except Exception:
        pass
    return out


async def fetch_json(url: str, headers: dict | None = None) -> dict:
    """GET an arbitrary URL (used for registry hosts). Returns {status, ok, json, text}."""
    h = {"User-Agent": _UA, "Accept": "application/json"}
    if headers:
        h.update(headers)
    resp = await _fetch(url, h)
    text = await resp.text()
    out = {"status": resp.status, "ok": bool(resp.ok), "text": text, "json": None}
    try:
        out["json"] = json.loads(text)
    except Exception:
        pass
    return out


async def resolve_ref(token, owner: str, repo: str, ref: str) -> str | None:
    """Resolve a tag name to its commit SHA (deref annotated tags)."""
    enc = urllib.parse.quote(ref, safe="")
    r = await gh_get_json(token, f"/repos/{owner}/{repo}/git/ref/tags/{enc}")
    if r["status"] != 200 or not r["json"]:
        return None
    obj = r["json"].get("object", {})
    if obj.get("type") == "commit":
        return obj.get("sha")
    if obj.get("type") == "tag":
        r2 = await gh_get_json(token, f"/repos/{owner}/{repo}/git/tags/{obj.get('sha')}")
        if r2["json"]:
            return r2["json"].get("object", {}).get("sha")
    return None


async def list_tags(token, owner: str, repo: str, per_page: int = 100) -> list:
    """First page of tags: [{name, commit_sha}]."""
    r = await gh_get_json(token, f"/repos/{owner}/{repo}/tags?per_page={per_page}")
    if r["status"] != 200 or not isinstance(r["json"], list):
        return []
    return [
        {"name": t.get("name"), "commit_sha": (t.get("commit") or {}).get("sha")}
        for t in r["json"]
    ]


async def default_branch_sha(token, owner: str, repo: str) -> tuple[str | None, str | None]:
    """Return (branch_name, commit_sha) for the repo's default branch."""
    r = await gh_get_json(token, f"/repos/{owner}/{repo}")
    if r["status"] != 200 or not r["json"]:
        return None, None
    branch = r["json"].get("default_branch")
    if not branch:
        return None, None
    b = await gh_get_json(token, f"/repos/{owner}/{repo}/commits/{urllib.parse.quote(branch, safe='')}")
    sha = b["json"].get("sha") if b["json"] else None
    return branch, sha


async def resolve_commitish(token, owner: str, repo: str, ref: str) -> str | None:
    """Resolve a branch/tag/sha to a commit SHA via the Commits API."""
    r = await gh_get_json(token, f"/repos/{owner}/{repo}/commits/{urllib.parse.quote(ref, safe='')}")
    if r["status"] == 200 and r["json"]:
        return r["json"].get("sha")
    return None


async def get_tree(token, owner: str, repo: str, commit_sha: str, etag: str | None = None) -> dict:
    """Recursive git tree. Returns {status, not_modified, etag, entries, truncated}."""
    r = await gh_get_json(
        token, f"/repos/{owner}/{repo}/git/trees/{commit_sha}?recursive=1", etag=etag
    )
    if r["not_modified"]:
        return {"status": 304, "not_modified": True, "etag": etag, "entries": [], "truncated": False}
    entries = (r["json"] or {}).get("tree", []) if r["json"] else []
    return {
        "status": r["status"],
        "not_modified": False,
        "etag": r["etag"],
        "entries": entries,
        "truncated": bool((r["json"] or {}).get("truncated")) if r["json"] else False,
    }


async def get_file_at_ref(token, owner: str, repo: str, ref: str, path: str) -> str | None:
    """Read a single text file via the Contents API at a ref (used for package.json verify)."""
    p = urllib.parse.quote(path)
    ref_q = urllib.parse.quote(ref, safe="")
    r = await gh_get_json(token, f"/repos/{owner}/{repo}/contents/{p}?ref={ref_q}")
    if r["status"] == 200 and r["json"] and r["json"].get("encoding") == "base64":
        try:
            return b64decode(r["json"]["content"]).decode("utf-8", "replace")
        except Exception:
            return None
    return None


async def get_raw_file(token, owner: str, repo: str, commit_sha: str, path: str) -> bytes | None:
    """Fetch file bytes via raw.githubusercontent (does not consume core API rate)."""
    # Encode each path segment but keep the slashes.
    safe_path = "/".join(urllib.parse.quote(seg) for seg in path.split("/"))
    url = f"{RAW}/{owner}/{repo}/{commit_sha}/{safe_path}"
    headers = {"User-Agent": _UA}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = await _fetch(url, headers)
    if not resp.ok:
        return None
    buf = await resp.arrayBuffer()
    return bytes(Uint8Array.new(buf).to_py())


async def get_blob(token, owner: str, repo: str, blob_sha: str) -> bytes | None:
    """Fetch file bytes by git blob SHA via the Blobs API (base64)."""
    r = await gh_get_json(token, f"/repos/{owner}/{repo}/git/blobs/{blob_sha}")
    if r["status"] == 200 and r["json"] and r["json"].get("encoding") == "base64":
        try:
            return b64decode(r["json"]["content"])
        except Exception:
            return None
    return None


def normalize_repo_url(url: str) -> tuple[str, str] | None:
    """Extract (owner, repo) from the many repository.url shapes npm/PyPI use.

    Handles: 'github:owner/repo', 'owner/repo', 'git+https://github.com/o/r.git',
    'git://github.com/o/r.git', 'ssh://git@github.com/o/r.git',
    'https://github.com/o/r/tree/main/pkg'. Non-github hosts → None.
    """
    if not url or not isinstance(url, str):
        return None
    u = url.strip()
    if u.startswith("github:"):
        u = u[len("github:"):]
    u = re.sub(r"^git\+", "", u)
    m = re.search(r"github\.com[:/]+([^/]+)/([^/#?]+)", u)
    if m:
        owner, repo = m.group(1), re.sub(r"\.git$", "", m.group(2))
        return owner, repo
    m2 = re.match(r"^([\w.-]+)/([\w.-]+?)(?:\.git)?$", u)
    if m2:
        return m2.group(1), m2.group(2)
    return None
