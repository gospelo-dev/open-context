# gospelo-open-context 最新仕様書 インデックス

> `docs/current/` 配下の最新仕様書へのポータルです。新しい仕様書を追加した場合は、必ずここにリンクを追記してください。

## 1. アーキテクチャ
- [x] [全体構成・設計原則](architecture/overview.md)
- [x] [データスキーマ・キャッシュレイアウト](architecture/data-schemas.md)
- [x] [認証(BYO PAT / OAuth 2.1)](architecture/auth.md)
- [x] [デプロイ・インフラ](architecture/deployment.md)

## 2. ツール
- [x] [MCP ツールリファレンス(6 tools)](tools/reference.md)

## 3. ソース参照(single source of truth)
- [worker/src/mcp_handler.py](../../worker/src/mcp_handler.py) — MCP 転送層 + 6 ツール実装 + 安全上限
- [worker/src/version_resolver.py](../../worker/src/version_resolver.py) — registry→tag→subdir 解決
- [worker/src/github_client.py](../../worker/src/github_client.py) — GitHub API クライアント
- [worker/src/cache_store.py](../../worker/src/cache_store.py) — R2 manifest / blob
- [worker/src/auth_resolver.py](../../worker/src/auth_resolver.py) — BYO PAT / OAuth 解決
- [worker/src/overrides.py](../../worker/src/overrides.py) — docs override 定義
- [worker/wrangler.jsonc](../../worker/wrangler.jsonc) — バインディング・vars

## 4. アーカイブ(gitignore・ローカルのみ)
- `development/docs/` — 初期設計ドキュメント(architecture / data-flow / infrastructure)
- `development/changelog/` — 更新ログ
- `development/scripts/` — コスト試算・docs 実測スクリプト
