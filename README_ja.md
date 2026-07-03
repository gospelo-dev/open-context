# gospelo-open-context

[![License: MIT](https://img.shields.io/badge/License-MIT-1E90FF.svg?style=flat)](https://github.com/gospelo-dev/open-context/blob/main/LICENSE) [![Python](https://img.shields.io/badge/Python-3.12+-1E90FF.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/) [![Cloudflare Workers](https://img.shields.io/badge/Cloudflare-Workers-F38020.svg?style=flat&logo=cloudflare&logoColor=white)](https://workers.cloudflare.com/) [![Auth](https://img.shields.io/badge/Auth-GitHub_token_(BYO)-2088FF.svg?style=flat&logo=github&logoColor=white)](https://github.com/gospelo-dev/open-context/blob/main/docs/current/architecture/auth.md) [![MCP](https://img.shields.io/badge/MCP-Claude_Code_%7C_Codex_%7C_Copilot_%7C_Cursor_%7C_OpenCode_%7C_LM_Studio-7B3FF2.svg?style=flat)](https://open-context.gospelo.dev/mcp)

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

**GitHub Copilot**(VS Code — `.vscode/mcp.json`。トークンは初回に一度だけ入力を求められ安全に保存される。ファイルには書かれない):
```json
{
  "inputs": [
    { "type": "promptString", "id": "open-context-token", "description": "open-context 用 GitHub PAT", "password": true }
  ],
  "servers": {
    "open-context": {
      "type": "http",
      "url": "https://open-context.gospelo.dev/mcp",
      "headers": { "X-GitHub-Token": "${input:open-context-token}" }
    }
  }
}
```
設定後、VS Code で **コマンドパレット → `MCP: List Servers` → `open-context` → Start** を実行し、プロンプトに GitHub PAT を入力(public パッケージならスコープ不要。private リポジトリを見る場合のみ `repo` を追加)。以後 Copilot Chat(エージェントモード)で `open-context` のツールが使え、`#open-context` で参照できる。

**Copilot CLI** は `~/.copilot/mcp-config.json`(同じ内容を `"mcpServers"` 配下に)、または `copilot mcp add --transport http --header "X-GitHub-Token: ghp_あなたのトークン" open-context https://open-context.gospelo.dev/mcp`。(MCP は Copilot Free/Pro ではポリシー変更不要。Business/Enterprise では組織側で MCP 許可が必要。)

**OpenCode**(user スコープは `~/.config/opencode/opencode.json`。プロジェクト直下の `opencode.json` にはトークンを書かない):
```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "open-context": {
      "type": "remote",
      "url": "https://open-context.gospelo.dev/mcp",
      "enabled": true,
      "headers": { "X-GitHub-Token": "{env:OPEN_CONTEXT_GH_TOKEN}" }
    }
  }
}
```
`{env:...}` は環境変数から展開されるためファイルにトークンは書かれない(生の `ghp_あなたのトークン` を直書きも可)。

**LM Studio**(`~/.lmstudio/mcp.json` — リモート MCP ホスト。トークンは生で保存されるためファイルは非公開に):
```json
{
  "mcpServers": {
    "open-context": {
      "url": "https://open-context.gospelo.dev/mcp",
      "headers": { "X-GitHub-Token": "ghp_あなたのトークン" }
    }
  }
}
```
その後 LM Studio アプリで、**tool-calling 対応モデル**をロードし、チャットのインテグレーション(🔌)で `open-context` を ON にする。`qwen2.5-coder-7b-instruct`(MLX)で動作確認済み — LM Studio がモデルのツール出力を構造化 tool call に変換するため `get_readme`/`list_contexts` が正しく発火する。(注: Ollama ランタイムは `qwen2.5-coder` の tool call を構造化**しない**。LM Studio を使うか、Ollama なら `qwen3` を使う。)

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

## 継続的な動作検証

毎日 GitHub Actions で(決定論的・**LLM 不使用・0 トークン**)主要パッケージを実サーバーに対して再チェックし、退行があれば Issue を起票します。各パッケージについて、版解決(正しい git tag)・README・版一致・docs 一覧・ファイル取得を検証します。

**版厳密のルール** — GitHub リポジトリがリリースに **git tag** を付けているパッケージが版厳密の対象です。resolver は一般的な形式に対応します: `v1.2.3` / `1.2.3` / `pkg@1.2.3`(monorepo)/ `pkg-1.2.3` / `rel_1_2_3`(SQLAlchemy 形式)。リポジトリがリリースに tag を切らない場合(changesets 系の一部など)はデフォルトブランチにフォールバックします — 有用ではありますが、厳密な版に固定はされません。

**監視対象** — 最新の一覧は [`quality/baseline.json`](https://github.com/gospelo-dev/open-context/blob/main/quality/baseline.json)。カテゴリ別内訳:

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
| `ui-components` | 4 |
| `webassembly` | 4 |
| `cli-tui` | 3 |
| `data-fetching` | 3 |
| `http-async` | 3 |
| `lint-format` | 3 |
| `mcp` | 3 |
| `state-management` | 3 |
| `agent` | 2 |
| `validation` | 2 |
| `animation` | 1 |
| `forms` | 1 |
| `infra-iac` | 1 |
| `styling` | 1 |
| **Total** | **82** |
<!-- END:monitored -->



**意図的に除外** — リリースに tag を付けないリポジトリ(例: Radix UI, SolidJS, SvelteKit の最新版, LangChain)は版厳密にできないため、デフォルトブランチを黙って返すのではなく除外しています。言語仕様(ES5)や OS シェル(bash/zsh)は設計上スコープ外です。

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
- [クライアント連携・tool-calling ガイド](https://github.com/gospelo-dev/open-context/blob/main/docs/current/clients/tool-calling.md)

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
