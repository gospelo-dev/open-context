# gospelo-open-context

[![License: MIT](https://img.shields.io/badge/License-MIT-1E90FF.svg?style=flat)](https://github.com/gospelo-dev/open-context/blob/main/LICENSE) [![Python](https://img.shields.io/badge/Python-3.12+-1E90FF.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/) [![Cloudflare Workers](https://img.shields.io/badge/Cloudflare-Workers-F38020.svg?style=flat&logo=cloudflare&logoColor=white)](https://workers.cloudflare.com/)  [![Auth](https://img.shields.io/badge/Auth-GitHub_token_(BYO)-2088FF.svg?style=flat&logo=github&logoColor=white)](https://github.com/gospelo-dev/open-context/blob/main/docs/current/architecture/auth.md)
[![MCP](https://img.shields.io/badge/MCP-Claude_Code_%7C_Codex_%7C_Cursor-7B3FF2.svg?style=flat)](https://open-context.gospelo.dev/mcp)

<p align="center"><img src="https://raw.githubusercontent.com/gospelo-dev/open-context/main/assets/hero.jpg" alt="Open Context — secure, version-precise docs & code for coding agents" width="820"></p>

**Version-precise package documentation and source code for coding agents — over MCP.**

A remote [Model Context Protocol](https://modelcontextprotocol.io) server that gives your coding agent the docs, types, examples, and source of a dependency **at the exact version your project uses** — fetched from GitHub at the matching git tag, not from stale training data or a "latest" snapshot. Inspired by [rtfmbro](https://github.com/marckrenn/rtfmbro-mcp) and reimplemented from scratch on Cloudflare Python Workers (GitHub API + R2 content-addressed cache) — an open-source, auditable, self-hostable alternative to Context7.

- **Hosted endpoint:** `https://open-context.gospelo.dev/mcp`
- **Auth:** bring your own GitHub token (BYO PAT) — your account, your rate limit, your repo access
- 日本語版: [README_ja.md](https://github.com/gospelo-dev/open-context/blob/main/README_ja.md)

---

## Why

LLMs suggest APIs from whatever version they were trained on — often the wrong one. Doc tools that pre-scrape have update lag and can serve the wrong version. `gospelo-open-context` resolves the **exact installed version** to its git tag and returns:

- **Not just docs** — also source, `.d.ts`/`.pyi` type definitions, `examples/`, and tests, so the agent sees the real signatures and usage for *that* version.
- **Version-precise** — no update lag, no wrong-version hallucinations.
- **Your own GitHub token** — requests run under your account's 5,000 req/h and your permissions (public by default; private repos with the right scope).

---

## Quickstart (BYO token)

1. Create a GitHub token — for public packages a **classic PAT with no scopes** is enough. ([github.com/settings/tokens](https://github.com/settings/tokens); add `repo` only if you need private repos.)

2. Add the server to your MCP client:

**Claude Code** (user scope — not committed):
```bash
claude mcp add --transport http --scope user open-context \
  https://open-context.gospelo.dev/mcp \
  --header "X-GitHub-Token: ghp_your_token"
```

**Codex** (`~/.codex/config.toml`, requires `experimental_use_rmcp_client`):
```toml
[mcp_servers.open-context]
url = "https://open-context.gospelo.dev/mcp"
bearer_token_env_var = "OPEN_CONTEXT_GH_TOKEN"   # export your GitHub token
```

Any MCP client that supports remote (Streamable HTTP) servers with custom headers works. Never commit a config file that contains your token.

---

## Tools

| Tool | Purpose |
|---|---|
| `list_contexts` | List supported ecosystems and curated docs overrides |
| `get_readme` | README at an exact version |
| `get_documentation_tree` | Doc/source file tree (scope=docs or all) |
| `read_files` | Read docs, source, types, examples by path + line range |
| `grep_repo` | Search within the pinned version (literal or regex) |
| `get_outline` | Markdown/code outline with line ranges (token-efficient) |

Typical flow: `get_readme` → `get_documentation_tree` → `get_outline` → `read_files` (or `grep_repo` to find a symbol). All tools take `package`, `version`, and optional `ecosystem` (`npm` default, or `pypi`). Pass the **actually installed** version (from your lockfile / `node_modules/{pkg}/package.json`), not a semver range.

---

## Supported ecosystems

- **npm** and **PyPI** — any package that resolves to a public GitHub repo works.
- Monorepo packages (e.g. `next`) are located by matching `package.json` name/version to find the right subdirectory.
- **Docs overrides**: for libraries whose prose docs live in a separate repo, code stays version-precise while docs come from the docs repo — currently `react` / `react-dom` (reactjs/react.dev), `astro` (withastro/docs), `typescript` (microsoft/TypeScript-Website). Adding one is a single entry in `worker/src/overrides.py`.

---

## Continuous verification

A daily GitHub Actions job (deterministic, **no LLM, zero tokens**) re-checks a set of popular packages against the live server and opens an issue on any regression. For each package it verifies version resolution (correct git tag), README, version match, docs tree, and file reads.

**Version-precision rule** — a package is version-precise when its GitHub repo publishes a **git tag** for the release. The resolver matches common conventions: `v1.2.3`, `1.2.3`, `pkg@1.2.3` (monorepos), `pkg-1.2.3`, `rel_1_2_3` (SQLAlchemy-style). If a repo does **not** tag releases (some changesets-based projects), the server falls back to the default branch — still useful, but not pinned to the exact version.

**What's monitored** — the live list is [`quality/baseline.json`](https://github.com/gospelo-dev/open-context/blob/main/quality/baseline.json). Breakdown by category:

<!-- BEGIN:monitored (auto-generated from quality/baseline.json — do not edit by hand) -->
| Category | Count |
|---|---|
| `frontend-framework` | 9 |
| `orm-db` | 6 |
| `rag-vectordb` | 6 |
| `build-tool` | 5 |
| `package-manager` | 5 |
| `rag-ml` | 5 |
| `ai-sdk` | 4 |
| `backend-framework` | 4 |
| `testing` | 4 |
| `webassembly` | 4 |
| `cli-tui` | 3 |
| `data-fetching` | 3 |
| `http-async` | 3 |
| `lint-format` | 3 |
| `mcp` | 3 |
| `state-management` | 3 |
| `agent` | 2 |
| `ui-components` | 2 |
| `validation` | 2 |
| `animation` | 1 |
| `forms` | 1 |
| `infra-iac` | 1 |
| `styling` | 1 |
| **Total** | **80** |
<!-- END:monitored -->



**Intentionally excluded** — packages whose repos don't tag releases (e.g. Radix UI, SolidJS, SvelteKit's latest, LangChain) can't be version-precise, so they're left out rather than silently served from the default branch. Language specs (ES5) and OS shells (bash/zsh) are out of scope by design.

---

## Trust & security

This server receives your GitHub token, so it is designed to earn that trust — and to be auditable:

- **BYO tokens are not stored.** In BYO-PAT mode the token is validated once via `GET /user` and only a **SHA-256 hash → identity** mapping is cached (1 hour) in KV. The token itself is never persisted.
- **Per-user isolation.** Every GitHub call uses the caller's own token, rate limit, and permissions.
- **No hardcoded secrets.** Account IDs and secrets are kept out of the repo (see `.gitignore`).
- **Open & self-hostable.** Run your own instance for private repos / compliance — see [docs/current/architecture/deployment.md](https://github.com/gospelo-dev/open-context/blob/main/docs/current/architecture/deployment.md).

Report vulnerabilities via [SECURITY.md](https://github.com/gospelo-dev/open-context/blob/main/SECURITY.md).

---

## Documentation

Current specs live in [`docs/current/`](https://github.com/gospelo-dev/open-context/blob/main/docs/current/_index.md):

- [Architecture overview](https://github.com/gospelo-dev/open-context/blob/main/docs/current/architecture/overview.md)
- [Data schemas & cache layout](https://github.com/gospelo-dev/open-context/blob/main/docs/current/architecture/data-schemas.md)
- [Authentication (BYO PAT / OAuth)](https://github.com/gospelo-dev/open-context/blob/main/docs/current/architecture/auth.md)
- [Deployment & self-hosting](https://github.com/gospelo-dev/open-context/blob/main/docs/current/architecture/deployment.md)
- [Tool reference](https://github.com/gospelo-dev/open-context/blob/main/docs/current/tools/reference.md)

---

## Hosted service & self-hosting

The hosted endpoint (`open-context.gospelo.dev`) is provided **as-is, best-effort, with no warranty or SLA**. Your GitHub token is used only to call GitHub on your behalf and is **not stored** (see [Trust & security](#trust--security)).

For **internal, proprietary, or compliance-sensitive** use where routing tokens/requests through the hosted endpoint isn't acceptable, **self-host** — the code is MIT-licensed and runs on your own Cloudflare account ([deployment guide](https://github.com/gospelo-dev/open-context/blob/main/docs/current/architecture/deployment.md)).

Full hosted-service terms: [TERMS.md](https://github.com/gospelo-dev/open-context/blob/main/TERMS.md).

---

## Acknowledgements

Version-aware documentation for coding agents was pioneered by [Context7](https://github.com/upstash/context7) (Upstash) and [rtfmbro](https://github.com/marckrenn/rtfmbro-mcp), and this project happily relied on Context7 for over a year.

We built `gospelo-open-context` because we wanted to use it **inside our own organization**. Sending GitHub tokens and proprietary-project context to a third-party service is a security concern, so we needed something **open, auditable, and self-hostable** — where tokens and traffic stay within our own infrastructure. It is our open take on the same idea, built with genuine respect and gratitude to both projects.

---

## License

Code: [MIT](https://github.com/gospelo-dev/open-context/blob/main/LICENSE). Hosted service: [TERMS.md](https://github.com/gospelo-dev/open-context/blob/main/TERMS.md).
