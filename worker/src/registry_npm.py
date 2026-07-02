"""
npm registry resolution: package + version -> GitHub {owner, repo, subdir}.

Reads registry.npmjs.org. Prefers the version-specific manifest (its
repository/directory can differ from 'latest' for monorepos).
"""

import github_client


def _encode(package: str) -> str:
    """URL-encode a package name (scoped '@scope/name' -> '@scope%2Fname')."""
    return package.replace("/", "%2F")


def _extract_repo(manifest: dict) -> tuple[str, str, str] | None:
    """From an npm manifest dict, return (owner, repo, subdir) or None."""
    if not manifest:
        return None
    repo_field = manifest.get("repository")
    url = None
    directory = ""
    if isinstance(repo_field, str):
        url = repo_field
    elif isinstance(repo_field, dict):
        url = repo_field.get("url")
        directory = repo_field.get("directory") or ""
    parsed = github_client.normalize_repo_url(url) if url else None
    if not parsed:
        return None
    owner, repo = parsed
    return owner, repo, directory.strip("/")


async def get_repo(token, package: str, version: str) -> dict | None:
    """Resolve npm package@version to {owner, repo, subdir}.

    Tries the version-specific manifest first, then the full packument.
    """
    enc = _encode(package)

    # Version-specific manifest (best source of repository.directory).
    ver = await github_client.fetch_json(f"https://registry.npmjs.org/{enc}/{version}")
    if ver["ok"] and isinstance(ver["json"], dict):
        got = _extract_repo(ver["json"])
        if got:
            owner, repo, subdir = got
            return {"owner": owner, "repo": repo, "subdir": subdir}

    # Fallback: full packument (top-level repository, and versions[version]).
    full = await github_client.fetch_json(f"https://registry.npmjs.org/{enc}")
    if full["ok"] and isinstance(full["json"], dict):
        versions = full["json"].get("versions") or {}
        vm = versions.get(version)
        got = _extract_repo(vm) if isinstance(vm, dict) else None
        if not got:
            got = _extract_repo(full["json"])
        if got:
            owner, repo, subdir = got
            return {"owner": owner, "repo": repo, "subdir": subdir}

    return None
