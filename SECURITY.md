# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report privately via GitHub's **[Report a vulnerability](https://github.com/gospelo-dev/open-context/security/advisories/new)** (Security → Advisories) on this repository. Include steps to reproduce and impact. We aim to acknowledge reports within a few business days on a best-effort basis.

## Supported versions

This project is deployed continuously from `main`. Fixes land on `main` and are redeployed; there are no long-lived release branches to backport to.

## Security model

`gospelo-open-context` receives a GitHub token from each user and calls the GitHub API on their behalf. Key properties (see [docs/current/architecture/auth.md](docs/current/architecture/auth.md) and [data-schemas.md](docs/current/architecture/data-schemas.md)):

- **BYO tokens are not stored.** In BYO-PAT mode the token is validated once via `GET /user`; only a SHA-256 **hash → identity** mapping is cached (1 hour) in KV. The raw token is never persisted.
- **Per-user isolation.** Every GitHub request uses the caller's own token, rate limit, and permissions. There is no shared server-side token.
- **OAuth mode** (optional, off by default) stores each user's GitHub token **AES-GCM encrypted** in KV, keyed by the user's GitHub id.
- **No hardcoded secrets.** Account IDs and secrets are kept out of the repository; runtime secrets are provided via Cloudflare Worker secrets / environment variables.
- **Auth gate.** In production, unauthenticated `/mcp` requests receive `401` + `WWW-Authenticate`. The development bypass (`X-Debug-Github-Token`) is only active when `ENVIRONMENT=development`.

## Recommendations for users

- For **public** packages, use a **classic PAT with no scopes** (or a fine-grained token with read-only access). Add `repo` (classic) or read-only Contents (fine-grained) only if you need private repositories.
- Do **not** commit config files (e.g. `.mcp.json`) that contain your token.
- Prefer short token expirations and rotate tokens periodically. Revoke a token if it may have been exposed.

## Self-hosting

You can run your own instance to keep tokens and traffic within your own Cloudflare account — see [docs/current/architecture/deployment.md](docs/current/architecture/deployment.md).
