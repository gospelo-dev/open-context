# デプロイ・インフラ

> 最終更新: 2026-07-02

---

## 1. リソース(Cloudflare、アカウント: Yuriko-hayakawa)

| 種別 | 名前 / binding | 備考 |
|---|---|---|
| Worker | `gospelo-open-context` | Python Worker(`python_workers`)、`cpu_ms: 300000` |
| カスタムドメイン | `open-context.gospelo.dev` | `routes` で custom_domain |
| R2 バケット | `open-context-cache`(binding `CACHE`) | manifest + blob |
| KV 名前空間 | `open-context-AUTH_KV`(binding `AUTH_KV`, id `24aef090…`) | chart-banana の `AUTH_KV` とは分離 |

`account_id` は wrangler.jsonc に**置かず**、`CLOUDFLARE_ACCOUNT_ID` 環境変数で渡す。

---

## 2. 環境変数 / secrets

| 名前 | 種別 | 用途 | 状態 |
|---|---|---|---|
| `ENVIRONMENT` | var | `production`(認証ゲート有効)。ローカルは `.dev.vars` で `development` | 設定済み |
| `APP_VERSION` / `DEPLOY_COMMIT` | var | バージョン表示(応答末尾の `server:` 行) | 設定済み |
| `SESSION_ENCRYPTION_KEY` | secret | OAuth 経路のトークン暗号化(AES-GCM 32byte) | 設定済み |
| `GITHUB_OAUTH_CLIENT_ID` / `_SECRET` | secret | OAuth 2.1(任意経路) | 未設定(BYO PAT は不要) |
| `CLOUDFLARE_ACCOUNT_ID` | env(デプロイ時) | wrangler のアカウント指定 | デプロイシェルで export |

> BYO PAT のみで運用する場合、GitHub OAuth の secret は不要。`SESSION_ENCRYPTION_KEY` も BYO PAT では未使用(害はない)。

---

## 3. デプロイ手順

```bash
cd worker
export CLOUDFLARE_ACCOUNT_ID=<account-id>

# 初回のみ: リソース作成
npx wrangler r2 bucket create open-context-cache
npx wrangler kv namespace create open-context-AUTH_KV   # 返る id を wrangler.jsonc に記入

# secret(OAuth を使う場合のみ)
openssl rand -base64 32 | npx wrangler secret put SESSION_ENCRYPTION_KEY
npx wrangler secret put GITHUB_OAUTH_CLIENT_ID
npx wrangler secret put GITHUB_OAUTH_CLIENT_SECRET

# デプロイ
uv run pywrangler deploy --var DEPLOY_COMMIT:$(git rev-parse --short HEAD)
```

**注意**: `ENVIRONMENT` は必ず `production` でデプロイすること(`development` のまま上げると認証バイパスが本番で有効化される)。ローカル dev は `worker/.dev.vars`(gitignore 済み)の `ENVIRONMENT=development` で上書きする。

デプロイ前に **identity check**(`gospelo-identity check`)で git/gh が `gospelo`(gorosun)であることを確認する。

---

## 4. ローカル開発

```bash
cd worker
uv sync              # dev 依存(pytest 等)
npm install          # wrangler
uv run pywrangler dev --port 8787   # http://localhost:8787
uv run pytest -q     # ユニットテスト(pyodide 非依存の純関数)
```

- `.dev.vars` に `ENVIRONMENT=development`(+ 任意で `CLOUDFLARE_ACCOUNT_ID`)
- dev では `X-Debug-Github-Token` ヘッダーで OAuth なしにツールを試せる

---

## 5. スモークテスト

```bash
BASE=https://open-context.gospelo.dev
curl -s $BASE/health                                   # {"status":"ok"}
curl -s $BASE/.well-known/oauth-protected-resource     # RFC 9728 メタデータ
curl -s -o /dev/null -w '%{http_code}\n' $BASE/mcp \
  -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'  # 401(本番ゲート)
curl -s $BASE/mcp -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -H "X-GitHub-Token: <token>" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_readme","arguments":{"package":"zod","version":"3.24.1","ecosystem":"npm"}}}'
```

---

## 6. コスト概観

R2 の egress 無料 + blob デデュープにより、中規模まで実質 Workers 基本料($5/月)。スケール上の制約は金額ではなく GitHub API レート制限だが、**BYO PAT でユーザーごとに 5,000 req/h に分散**されるため実質的に解消している。詳細な試算は `development/scripts/cost.py`(ローカル)を参照。
