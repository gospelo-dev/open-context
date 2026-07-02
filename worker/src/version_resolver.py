"""
Version resolution: (package, version, ecosystem) -> pinned GitHub location.

Pipeline: resolve-cache -> registry(repo+subdir) -> tag match -> package.json
verification gate (monorepo safety) -> persist. Returns a `pin`:

    {ecosystem, package, version, owner, repo, subdir,
     tag, commit_sha, verified, warning}
"""

import re
import time

import cache_store
import github_client
import overrides
import registry_npm
import registry_pypi


class ResolveError(Exception):
    pass


def _candidate_tags(version: str, package: str) -> list[str]:
    """Ordered tag-name candidates covering common conventions."""
    # For scoped names, the monorepo tag usually uses the bare (unscoped) name.
    short = package.split("/")[-1] if package.startswith("@") else package
    cands = [
        f"v{version}",
        version,
        f"{package}@{version}",          # npm monorepo (changesets/lerna)
        f"{short}@{version}",
        f"{package}-v{version}",
        f"{short}-v{version}",
        f"{package}-{version}",          # python style (e.g. Django-5.0)
        f"{short}-{version}",
        f"release-{version}",
        f"rel_{version.replace('.', '_')}",   # SQLAlchemy style (rel_2_0_51)
    ]
    seen = set()
    out = []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _digits(s: str) -> str:
    return re.sub(r"[^0-9.]", "", s or "")


async def _match_tag(token, owner, repo, version, package) -> dict | None:
    """Return {tag, commit_sha} or None."""
    for cand in _candidate_tags(version, package):
        sha = await github_client.resolve_ref(token, owner, repo, cand)
        if sha:
            return {"tag": cand, "commit_sha": sha}
    # Fuzzy fallback across the first page of tags.
    target = _digits(version)
    for t in await github_client.list_tags(token, owner, repo):
        if _digits(t["name"]) == target and t.get("commit_sha"):
            return {"tag": t["name"], "commit_sha": t["commit_sha"]}
    return None


async def _verify_pkg_json(token, owner, repo, subdir, tag, version, package) -> tuple[bool, str | None, str]:
    """Locate & verify the package's package.json at the tag (npm monorepo gate).

    npm often omits repository.directory (e.g. `next`), so we probe common
    monorepo layouts and identify the right subdir by matching name/version.

    Returns (verified, warning, subdir) — subdir may be corrected.
    """
    import json as _json

    short = package.split("/")[-1] if package.startswith("@") else package
    candidates: list[str] = []
    for c in ([subdir] if subdir else []) + ["", f"packages/{short}"]:
        if c not in candidates:
            candidates.append(c)

    name_match = None  # (subdir, version) when name matches but version differs
    for cand in candidates:
        path = f"{cand}/package.json" if cand else "package.json"
        raw = await github_client.get_file_at_ref(token, owner, repo, tag, path)
        if not raw:
            continue
        try:
            pj = _json.loads(raw)
        except Exception:
            continue
        nm, vr = pj.get("name"), pj.get("version")
        if nm == package and vr == version:
            return True, None, cand
        if nm == package and name_match is None:
            name_match = (cand, vr)

    if name_match is not None:
        cand, vr = name_match
        return False, (
            f"repo package.json version {vr} != requested {version} "
            f"at {owner}/{repo}@{tag} (monorepo tag may be shared)"
        ), cand

    return False, f"could not verify package.json for '{package}' at {owner}/{repo}@{tag}", subdir


async def resolve(env, token, package: str, version: str, ecosystem: str) -> dict:
    """Resolve to a pinned GitHub location, using and updating the R2 resolve cache."""
    r2 = getattr(env, "CACHE", None)

    cached = await cache_store.get_resolve_cache(r2, ecosystem, package, version)
    if cached and (time.time() - cached.get("cached_at", 0)) < cache_store.RESOLVE_TTL_SECONDS:
        return cached

    if ecosystem == "npm":
        repo_info = await registry_npm.get_repo(token, package, version)
    elif ecosystem == "pypi":
        repo_info = await registry_pypi.get_repo(token, package, version)
    else:
        raise ResolveError(f"ecosystem '{ecosystem}' not supported (supported: npm, pypi)")

    if not repo_info:
        raise ResolveError(
            f"could not find a GitHub repository for {ecosystem} package '{package}'. "
            "The package may lack a repository/source URL or use a non-GitHub host."
        )
    owner, repo, subdir = repo_info["owner"], repo_info["repo"], repo_info["subdir"]

    match = await _match_tag(token, owner, repo, version, package)
    if match:
        tag, commit_sha = match["tag"], match["commit_sha"]
        if ecosystem == "npm":
            verified, warning, subdir = await _verify_pkg_json(
                token, owner, repo, subdir, tag, version, package
            )
        else:
            # PyPI: single-package-per-repo is the norm; tag match is sufficient.
            verified, warning = True, None
    else:
        branch, commit_sha = await github_client.default_branch_sha(token, owner, repo)
        if not commit_sha:
            raise ResolveError(
                f"no tag matched version {version} and no default branch found for {owner}/{repo}"
            )
        tag, verified = branch, False
        warning = f"no tag matched version {version}; using default branch '{branch}'"

    pin = {
        "ecosystem": ecosystem,
        "package": package,
        "version": version,
        "owner": owner,
        "repo": repo,
        "subdir": subdir or "",
        "tag": tag,
        "commit_sha": commit_sha,
        "verified": verified,
        "warning": warning,
        "docs_pin": None,
        "cached_at": int(time.time()),
    }

    # Curated docs override: docs live in a separate (usually unversioned) repo.
    ov = overrides.get_override(ecosystem, package)
    if ov and ov.get("docs"):
        d = ov["docs"]
        d_owner, _, d_repo = d["repo"].partition("/")
        d_ref = d.get("ref", "main")
        d_sha = await github_client.resolve_commitish(token, d_owner, d_repo, d_ref)
        if d_sha:
            pin["docs_pin"] = {
                "owner": d_owner,
                "repo": d_repo,
                "subdir": (d.get("subdir") or "").strip("/"),
                "ref": d_ref,
                "commit_sha": d_sha,
            }

    await cache_store.put_resolve_cache(r2, ecosystem, package, version, pin)
    return pin
