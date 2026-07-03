"""
Curated overrides for the "supported contexts" that can't be auto-resolved
from the registry alone.

Kept as a plain Python dict (zero-dependency, comment-friendly, IDE-checkable,
fastest to load — no runtime parse). Build-time config: edit + redeploy. If we
ever need live editing without a deploy, move OVERRIDES into KV.

Keys are "{ecosystem}:{package}". The common case is docs living in a SEPARATE
repository from the code (handbooks / doc sites). Those doc repos are usually
NOT tagged per release, so `ref` is a branch (docs are served unversioned with
a warning; code stays version-precise from the registry tag).
"""

ECOSYSTEMS = {
    "npm": {"registry": "https://registry.npmjs.org"},
    "pypi": {"registry": "https://pypi.org/pypi"},
}

# docs: {repo: "owner/name", subdir: "...", ref: "branch-or-tag"}
OVERRIDES = {
    "npm:react": {
        "docs": {"repo": "reactjs/react.dev", "subdir": "src/content", "ref": "main"},
    },
    "npm:react-dom": {
        "docs": {"repo": "reactjs/react.dev", "subdir": "src/content", "ref": "main"},
    },
    "npm:astro": {
        "docs": {"repo": "withastro/docs", "subdir": "src/content/docs", "ref": "main"},
    },
    "npm:typescript": {
        "docs": {
            "repo": "microsoft/TypeScript-Website",
            "subdir": "packages/documentation/copy/en",
            "ref": "v2",
        },
    },
    # The `shadcn` npm package is the CLI (repository.directory = packages/shadcn,
    # source only). Real docs live in the site app under apps/v4.
    "npm:shadcn": {
        "docs": {"repo": "shadcn-ui/ui", "subdir": "apps/v4/content/docs", "ref": "main"},
    },
    # @base-ui-components/react resolves to packages/react (source). Docs are the
    # Next.js content route group under docs/src/app/(docs)/react.
    "npm:@base-ui-components/react": {
        "docs": {
            "repo": "mui/base-ui",
            "subdir": "docs/src/app/(docs)/react",
            "ref": "master",
        },
    },
}


def get_override(ecosystem: str, package: str) -> dict | None:
    return OVERRIDES.get(f"{ecosystem}:{package}")
