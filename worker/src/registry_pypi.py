"""
PyPI resolution: package + version -> GitHub {owner, repo, subdir}.

Reads pypi.org JSON API. PyPI has no monorepo `directory` concept, so subdir
is always "" (single-package-per-repo is the norm). The GitHub URL is found in
info.project_urls / info.home_page.
"""

import github_client

# project_urls keys (lowercased) most likely to point at the source repo,
# in priority order.
_URL_KEY_PRIORITY = (
    "source", "source code", "sourcecode", "repository", "code",
    "github", "home", "homepage", "documentation", "docs",
)


def _extract_repo(info: dict) -> tuple[str, str] | None:
    if not info:
        return None
    project_urls = info.get("project_urls") or {}
    lowered = {str(k).lower(): v for k, v in project_urls.items()}

    ordered = []
    for key in _URL_KEY_PRIORITY:
        if key in lowered:
            ordered.append(lowered[key])
    if info.get("home_page"):
        ordered.append(info["home_page"])
    # Fall back to scanning every declared URL.
    ordered.extend(project_urls.values())

    for url in ordered:
        parsed = github_client.normalize_repo_url(url) if isinstance(url, str) else None
        if parsed:
            return parsed
    return None


async def get_repo(token, package: str, version: str) -> dict | None:
    """Resolve PyPI package@version to {owner, repo, subdir}."""
    for url in (
        f"https://pypi.org/pypi/{package}/{version}/json",
        f"https://pypi.org/pypi/{package}/json",
    ):
        r = await github_client.fetch_json(url)
        if r["ok"] and isinstance(r["json"], dict):
            got = _extract_repo(r["json"].get("info") or {})
            if got:
                owner, repo = got
                return {"owner": owner, "repo": repo, "subdir": ""}
    return None
