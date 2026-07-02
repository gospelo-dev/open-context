# Terms of Use — Hosted Service

_Last updated: 2026-07-02 · 日本語: [TERMS_ja.md](TERMS_ja.md)_

These terms cover the **hosted service** at `https://open-context.gospelo.dev`. They do **not** govern the source code — the code is provided under the [MIT License](LICENSE), which lets you run your own instance. If any of the terms below are unacceptable for your use case, **self-host instead** (see [Self-hosting](#self-hosting)).

## 1. As-is, no warranty, no SLA

The hosted service is provided on a **best-effort, "as-is" basis, with no warranty and no service-level agreement**. Availability, performance, and correctness are not guaranteed. The service may change, rate-limit, or be discontinued at any time without notice.

## 2. Your GitHub token and data

- You supply your **own GitHub token** (BYO). It is used solely to call the GitHub API **on your behalf** to fetch package documentation and source.
- **Tokens are not stored.** In BYO-token mode the token is validated once and only a **SHA-256 hash → identity** mapping is cached (~1 hour). The raw token is never persisted. (Optional OAuth mode stores the token AES-GCM-encrypted; off by default.)
- Your tokens and identity are **not sold or shared** with third parties.
- Requests necessarily transit **GitHub** (api.github.com / raw / codeload) and **Cloudflare** (the hosting platform). Their respective terms and privacy policies apply to that traffic.
- See [SECURITY.md](SECURITY.md) for the security model and vulnerability reporting.

## 3. Acceptable use

- Requests run under **your own** GitHub token, rate limit, and permissions. You are responsible for the scope you grant your token (use the minimum needed).
- Do not abuse, overload, or attempt to disrupt the service, and do not use it to access content you are not authorized to access.
- Respect **GitHub's Terms of Service and API rate limits**.
- The documentation and source code that is retrieved and returned belongs to its **respective repository owners under their own licenses**. This service is only a retrieval conduit and grants you no rights to that content; you are responsible for using it in accordance with each project's license.

## 4. Self-hosting

If routing your tokens or requests through the hosted endpoint is unacceptable for your organization — for example internal, proprietary, or compliance-sensitive use — **run your own instance**. The code is open source (MIT); see the [deployment guide](docs/current/architecture/deployment.md). Self-hosting is the recommended option for such cases, and keeps all tokens and traffic within your own infrastructure.

## 5. Limitation of liability

To the maximum extent permitted by law, the maintainers are **not liable** for any direct, indirect, incidental, or consequential damages arising from use of (or inability to use) the hosted service. This reinforces, in the service context, the warranty disclaimer of the [MIT License](LICENSE).

## 6. Changes

These terms may be updated over time; the current version lives in this repository. Continued use of the hosted service after changes constitutes acceptance. Questions and issues: the [project repository](https://github.com/gospelo-dev/open-context).
