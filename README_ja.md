# gospelo-open-context

[![License: MIT](https://img.shields.io/badge/License-MIT-1E90FF.svg?style=flat)](https://github.com/gospelo-dev/open-context/blob/main/LICENSE) [![Python](https://img.shields.io/badge/Python-3.12+-1E90FF.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/) [![Cloudflare Workers](https://img.shields.io/badge/Cloudflare-Workers-F38020.svg?style=flat&logo=cloudflare&logoColor=white)](https://workers.cloudflare.com/) [![Auth](https://img.shields.io/badge/Auth-GitHub_token_(BYO)-2088FF.svg?style=flat&logo=github&logoColor=white)](https://github.com/gospelo-dev/open-context/blob/main/docs/current/architecture/auth.md) [![MCP](https://img.shields.io/badge/MCP-Claude_Code_%7C_Codex_%7C_Cursor-7B3FF2.svg?style=flat)](https://open-context.gospelo.dev/mcp)

<p align="center"><img src="https://raw.githubusercontent.com/gospelo-dev/open-context/main/assets/hero.jpg" alt="Open Context — セキュアでバージョン厳密な docs とコードをコーディングエージェントへ" width="820"></p>

**コーディングエージェントへ、バージョン厳密なパッケージのドキュメント/ソースコードを MCP で供給する。**

[Model Context Protocol](https://modelcontextprotocol.io) のリモートサーバー。依存パッケージの docs・型・examples・ソースを、**プロジェクトが実際に使っている版そのもの**で(学習データや「最新版」ではなく、一致する git tag から)取得します。[rtfmbro](https://github.com/marckrenn/rtfmbro-mcp) に着想を得て Cloudflare Python Workers 上に GitHub API + R2 コンテンツアドレスキャッシュでゼロから再実装した、**オープンで監査可能・自社運用可能な Context7 の代替**です。

- **ホスト版エンドポイント:** `https://open-context.gospelo.dev/mcp`
- **認証:** 各ユーザー自身の GitHub トークン(BYO PAT)— 自分のアカウント・レート制限・リポジトリ権限で動作
- English: [README.md](https://github.com/gospelo-dev/open-context/blob/main/README.md)

---

## なぜ必要か

LLM は学習時点の版の API を提案しがちで、しばしば間違った版になります。事前スクレイプ型の docs ツールは更新遅延があり、誤った版を返すこともあります。`gospelo-open-context` は**実インストール版**を git tag に解決し、次を返します:

- **docs だけでなく**、ソース・`.d.ts`/`.pyi` 型定義・`examples/`・テストも。その版の正確なシグネチャと実使用例が得られます。
- **バージョン厳密** — 更新遅延なし、誤った版の提案が起きません。
- **各自の GitHub トークン** — あなたのアカウントの 5,000 req/h と権限で実行(既定は public、スコープを付ければ private も)。

---

## クイックスタート(BYO トークン)

1. GitHub トークンを発行 — public 用途なら **スコープなしの classic PAT** で十分([github.com/settings/tokens](https://github.com/settings/tokens)、private を見るなら `repo` を追加)。

2. MCP クライアントに追加:

**Claude Code**(user スコープ・非コミット):
```bash
claude mcp add --transport http --scope user open-context \
  https://open-context.gospelo.dev/mcp \
  --header "X-GitHub-Token: ghp_あなたのトークン"
```

**Codex**(`~/.codex/config.toml`、要 `experimental_use_rmcp_client`):
```toml
[mcp_servers.open-context]
url = "https://open-context.gospelo.dev/mcp"
bearer_token_env_var = "OPEN_CONTEXT_GH_TOKEN"   # export に GitHub トークン
```

リモート(Streamable HTTP)+ カスタムヘッダー対応の MCP クライアントで利用可能。**トークンを含む設定ファイルはコミットしないこと**。

---

## ツール

| ツール | 役割 |
|---|---|
| `list_contexts` | 対応エコシステムと docs override の一覧 |
| `get_readme` | 指定版の README |
| `get_documentation_tree` | docs/ソースのツリー(scope=docs / all) |
| `read_files` | docs・ソース・型・examples をパス + 行範囲で取得 |
| `grep_repo` | 指定版内を検索(リテラル / 正規表現) |
| `get_outline` | Markdown/コードの構造 + 行範囲(省トークン) |

標準フロー: `get_readme` → `get_documentation_tree` → `get_outline` → `read_files`(シンボル検索は `grep_repo`)。全ツールは `package`・`version`・任意の `ecosystem`(既定 `npm`、または `pypi`)を取ります。`version` は **実インストール版**(lockfile / `node_modules/{pkg}/package.json`)を渡してください(semver レンジではない)。

---

## 対応エコシステム

- **npm** と **PyPI** — public な GitHub リポジトリに解決できるパッケージが対象。
- monorepo(例: `next`)は `package.json` の name/version 照合で正しいサブディレクトリを特定。
- **docs override**: 散文ドキュメントが別リポジトリにあるライブラリは、コードは版厳密のまま docs のみ別 repo から取得 — 現在 `react` / `react-dom`(reactjs/react.dev)、`astro`(withastro/docs)、`typescript`(microsoft/TypeScript-Website)。追加は `worker/src/overrides.py` に1エントリ。

---

## 信頼とセキュリティ

本サーバーはあなたの GitHub トークンを受け取るため、その信頼に応える設計・監査可能性を重視しています:

- **BYO トークンは保存しません。** BYO-PAT 方式ではトークンを `GET /user` で一度だけ検証し、**SHA-256 ハッシュ → 識別情報**のみを KV に1時間キャッシュします。トークン自体は永続化しません。
- **ユーザーごとに分離。** すべての GitHub 呼び出しは呼び出し元自身のトークン・レート・権限で実行。
- **秘匿情報のハードコードなし。** アカウント ID や secret はリポジトリに含めません(`.gitignore` 参照)。
- **オープン & セルフホスト可能。** private repo / コンプラ用途に自前運用できます — [docs/current/architecture/deployment.md](https://github.com/gospelo-dev/open-context/blob/main/docs/current/architecture/deployment.md)。

脆弱性報告は [SECURITY.md](https://github.com/gospelo-dev/open-context/blob/main/SECURITY.md) を参照してください。

---

## ドキュメント

現行仕様は [`docs/current/`](https://github.com/gospelo-dev/open-context/blob/main/docs/current/_index.md):

- [全体構成・設計原則](https://github.com/gospelo-dev/open-context/blob/main/docs/current/architecture/overview.md)
- [データスキーマ・キャッシュレイアウト](https://github.com/gospelo-dev/open-context/blob/main/docs/current/architecture/data-schemas.md)
- [認証(BYO PAT / OAuth)](https://github.com/gospelo-dev/open-context/blob/main/docs/current/architecture/auth.md)
- [デプロイ・セルフホスト](https://github.com/gospelo-dev/open-context/blob/main/docs/current/architecture/deployment.md)
- [ツールリファレンス](https://github.com/gospelo-dev/open-context/blob/main/docs/current/tools/reference.md)

---

## ホスト版と自社運用

ホスト版エンドポイント(`open-context.gospelo.dev`)は **現状のまま・ベストエフォート・無保証・SLA なし**で提供します。GitHub トークンはあなたの代わりに GitHub を呼ぶためだけに使い、**保存しません**([信頼とセキュリティ](#信頼とセキュリティ)参照)。

**社内・機密・コンプライアンス要件**などで、トークンやリクエストをホスト版に通すのが許容できない場合は、**自社運用**してください — コードは MIT で、あなた自身の Cloudflare アカウントで動きます([デプロイ手順](https://github.com/gospelo-dev/open-context/blob/main/docs/current/architecture/deployment.md))。

ホスト版の利用規約全文: [TERMS.md](https://github.com/gospelo-dev/open-context/blob/main/TERMS.md)(参考和訳: [TERMS_ja.md](https://github.com/gospelo-dev/open-context/blob/main/TERMS_ja.md))。

---

## 謝辞

コーディングエージェント向けの「版に対応したドキュメント」は [Context7](https://github.com/upstash/context7)(Upstash)と [rtfmbro](https://github.com/marckrenn/rtfmbro-mcp) が切り拓きました。私たちは 1 年以上 Context7 に助けられてきました。

`gospelo-open-context` を作った動機は、これを**自社内で使いたかった**ことにあります。GitHub トークンや自社プロジェクトの文脈を第三者サービスに渡すことはセキュリティ上の懸念であり、**オープンで監査可能・自社運用可能**な——トークンも通信も自社インフラ内に留められる——ものが必要でした。本プロジェクトはその発想へのオープンな回答であり、両者への確かな敬意と感謝のもとに作っています。

---

## ライセンス

コード: [MIT](https://github.com/gospelo-dev/open-context/blob/main/LICENSE)(参考和訳: [LICENSE_ja.md](https://github.com/gospelo-dev/open-context/blob/main/LICENSE_ja.md))/ ホスト版: [TERMS.md](https://github.com/gospelo-dev/open-context/blob/main/TERMS.md)
