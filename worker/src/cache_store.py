"""
R2 cache for gospelo-open-context.

Layout (see development/docs/infrastructure.md):
    manifests/{ecosystem}/{package}/{version}.json  # commit_sha, tree_etag, files{path:{sha,size}}
    blobs/{blobSHA}                                  # file bytes (deduped across versions)
    resolve/{ecosystem}/{package}/{version}.json     # resolved pin (short TTL)

Blobs are keyed by git blob SHA -> unchanged files dedupe across versions.
R2 marshalling mirrors chart-banana sample_store.py.
"""

import json

try:  # pragma: no cover - real runtime is pyodide
    from js import Uint8Array
    from pyodide.ffi import to_js
except ImportError:  # pragma: no cover - CPython unit tests
    Uint8Array = None

    def to_js(obj, **_):
        return obj


RESOLVE_TTL_SECONDS = 86400  # 24h


def _enc(package: str) -> str:
    return package.replace("/", "%2F")


def manifest_key(ecosystem: str, package: str, version: str) -> str:
    return f"manifests/{ecosystem}/{_enc(package)}/{version}.json"


def blob_key(blob_sha: str) -> str:
    return f"blobs/{blob_sha}"


def docs_manifest_key(owner: str, repo: str, commit_sha: str) -> str:
    """Docs manifests are content-addressed by commit (immutable, deduped)."""
    return f"manifests/_docs/{owner}/{repo}/{commit_sha}.json"


async def get_docs_manifest(r2, owner, repo, commit_sha) -> dict | None:
    return await _get_json(r2, docs_manifest_key(owner, repo, commit_sha))


async def put_docs_manifest(r2, owner, repo, commit_sha, manifest: dict) -> None:
    await _put_json(r2, docs_manifest_key(owner, repo, commit_sha), manifest)


def resolve_key(ecosystem: str, package: str, version: str) -> str:
    return f"resolve/{ecosystem}/{_enc(package)}/{version}.json"


async def _get_json(r2, key: str) -> dict | None:
    if r2 is None:
        return None
    obj = await r2.get(key)
    if obj is None:
        return None
    try:
        return json.loads(await obj.text())
    except Exception:
        return None


async def _put_json(r2, key: str, data: dict) -> None:
    if r2 is None:
        return
    await r2.put(key, json.dumps(data, ensure_ascii=False))


async def get_manifest(r2, ecosystem, package, version) -> dict | None:
    return await _get_json(r2, manifest_key(ecosystem, package, version))


async def put_manifest(r2, ecosystem, package, version, manifest: dict) -> None:
    await _put_json(r2, manifest_key(ecosystem, package, version), manifest)


async def get_resolve_cache(r2, ecosystem, package, version) -> dict | None:
    return await _get_json(r2, resolve_key(ecosystem, package, version))


async def put_resolve_cache(r2, ecosystem, package, version, pin: dict) -> None:
    await _put_json(r2, resolve_key(ecosystem, package, version), pin)


def resolved_key(owner: str, repo: str, commit_sha: str, full_path: str) -> str:
    """Cache key for a file fetched directly by commit + path (commit is
    immutable, so this is a safe permanent cache without needing the git tree)."""
    return f"resolved/{owner}/{repo}/{commit_sha}/{full_path}"


async def get_file(r2, key: str) -> bytes | None:
    if r2 is None:
        return None
    obj = await r2.get(key)
    if obj is None:
        return None
    buf = await obj.arrayBuffer()
    if isinstance(buf, (bytes, bytearray)):
        return bytes(buf)
    return bytes(Uint8Array.new(buf).to_py())


async def put_file(r2, key: str, data: bytes, content_type: str = "text/plain") -> None:
    if r2 is None:
        return
    await r2.put(
        key,
        to_js(data),
        to_js({"httpMetadata": {"contentType": content_type}}),
    )


async def get_blob(r2, blob_sha: str) -> bytes | None:
    if r2 is None:
        return None
    obj = await r2.get(blob_key(blob_sha))
    if obj is None:
        return None
    buf = await obj.arrayBuffer()
    if isinstance(buf, (bytes, bytearray)):
        return bytes(buf)
    return bytes(Uint8Array.new(buf).to_py())


async def put_blob(r2, blob_sha: str, data: bytes, content_type: str = "text/plain") -> None:
    if r2 is None:
        return
    await r2.put(
        blob_key(blob_sha),
        to_js(data),
        to_js({"httpMetadata": {"contentType": content_type}}),
    )
