# データスキーマ・キャッシュレイアウト

> 最終更新: 2026-07-02

R2(コンテンツキャッシュ)と KV(認証)のキー設計・レコード構造をまとめる。

---

## 1. R2 レイアウト(バケット `open-context-cache`)

```
manifests/{ecosystem}/{package}/{version}.json   コード側 manifest(subdir 相対 + repo-root docs)
manifests/_docs/{owner}/{repo}/{commit_sha}.json  docs override manifest(commit で content-addressed)
blobs/{blobSHA}                                   ファイル内容(バージョン横断でデデュープ)
resolve/{ecosystem}/{package}/{version}.json      pin(バージョン解決結果、短 TTL)
```

- scoped npm 名の `/` は `%2F` にエンコードしてキーに使う(例 `@scope%2Fname`)
- **blob は git blob SHA をキーにする**ため、未変更ファイルは複数バージョン・複数 manifest から 1 つの blob を共有(自動デデュープ)

---

## 2. manifest スキーマ

`_get_or_build_manifest`(コード repo)が生成:

```jsonc
{
  "commit_sha": "dafcd43...",      // 解決した tag の commit
  "tree_etag": "W/\"...\"",         // GitHub tree の ETag(将来の再検証用)
  "generated_at": 1782...,          // epoch 秒
  "owner": "vercel",
  "repo": "next.js",
  "subdir": "packages/next",        // パッケージのサブディレクトリ(monorepo)
  "partial": false,                 // GitHub tree が truncate された場合 true
  "files": {                        // subdir 相対パス → {sha, size}
    "package.json": {"sha": "...", "size": 1234},
    "types/index.d.ts": {"sha": "...", "size": 5678}
  },
  "root_docs": {                    // repo 直下 docs(subdir 外)。read_files では '/' 接頭辞で参照
    "docs/01-app/.../installation.mdx": {"sha": "...", "size": 11216}
  }
}
```

docs override manifest(`_get_or_build_docs_manifest`)は `is_docs: true`、`ref`(ブランチ)を持ち、`files` は override subdir 相対のドキュメントのみ、`root_docs` は空。

### パス解決規約(`_resolve_entry`)

| パス形式 | 参照先 |
|---|---|
| `package.json`(接頭辞なし) | manifest の subdir 相対(コード) |
| `/docs/...`(`/` 接頭辞) | repo-root(`root_docs`)または docs override repo |

`read_files` / `get_outline` / `grep_repo` は **コード manifest と docs manifest を横断**して解決する。

---

## 3. pin スキーマ(バージョン解決結果)

`version_resolver.resolve` の戻り値、`resolve/{eco}/{pkg}/{ver}.json` にキャッシュ:

```jsonc
{
  "ecosystem": "npm",
  "package": "next",
  "version": "15.1.0",
  "owner": "vercel",
  "repo": "next.js",
  "subdir": "packages/next",
  "tag": "v15.1.0",
  "commit_sha": "dafcd43...",
  "verified": true,               // package.json の name/version 照合が通ったか
  "warning": null,                // 版不一致・default branch fallback 等の警告
  "docs_pin": {                   // docs override があれば別 repo の pin(なければ null)
    "owner": "reactjs", "repo": "react.dev",
    "subdir": "src/content", "ref": "main", "commit_sha": "..."
  },
  "cached_at": 1782...
}
```

- `verified=false` のときは `warning` に理由(monorepo で tag が共有・版不一致・tag 未発見で default branch 使用 等)が入り、ツール応答のヘッダーに `⚠️` として表示される
- resolve キャッシュ TTL は 24h(`cache_store.RESOLVE_TTL_SECONDS`)

---

## 4. KV レイアウト(名前空間 `AUTH_KV` = `open-context-AUTH_KV`)

| キー | 用途 | TTL |
|---|---|---|
| `byotok:{sha256(token)[:20]}` | **BYO PAT** 検証結果のキャッシュ(`{user_sub, login}`) | 1h |
| `access_token:{token}` | OAuth 発行 Bearer → `{user_sub, client_id, scope, resource, ...}` | 無期限(revoke=削除) |
| `oauth_client:{client_id}` | OAuth 動的クライアント登録(RFC 7591) | 無期限 |
| `oauth_code:{code}` | OAuth 認可コード(PKCE、ワンタイム) | 10 分 |
| `user:{user_sub}` | ユーザーレコード(`login` + 暗号化 GitHub トークン) | 無期限 |
| `session:{session_id}` | ブラウザセッション(OAuth 同意画面用) | 30 日 |

- BYO PAT のトークン自体は KV に保存しない(ハッシュのみキーに使用)
- OAuth 経路の GitHub トークンは AES-GCM で暗号化して `user:{user_sub}` に保存(`encryption.py`)

---

## 5. auth_context(ツールに渡る認証コンテキスト)

`auth_resolver.resolve_auth_context` の戻り値:

```jsonc
{ "user_sub": "12345", "login": "gorosun", "github_token": "ghp_..." }
```

- `github_token` が全 GitHub API 呼び出しに使われる(BYO=ユーザー自身のトークン、OAuth=復号したユーザーのトークン)
- `user_sub` は将来の per-user レート制限・濫用ガード用(現状は識別のみ)

---

## 6. 安全上限(`mcp_handler.py` 定数)

| 上限 | 値 | 位置 |
|---|---|---|
| MAX_FILE_SIZE | 1 MB/ファイル | manifest 構築で除外 |
| MAX_FILES_PER_READ | 20 req/呼出 | `read_files` |
| MAX_TOTAL_READ_BYTES | 2 MB/呼出 | `read_files` 累積 |
| MAX_LINE_RANGE | 2,000 行/スライス | `read_files` |
| RESPONSE_TRUNCATE | 100 KB/text ブロック | 全ツール |
| MAX_TREE_TOOL_OUTPUT | 1,500 paths | `get_documentation_tree` |
| MAX_GREP_FILES / _FETCH / _HITS | 400 / 80 / 100 | `grep_repo` |
| MAX_GREP_QUERY | 200 文字 | `grep_repo`(ReDoS 上限) |
| MAX_OUTLINE | 500 セクション | `get_outline` |
