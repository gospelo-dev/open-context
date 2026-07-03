# クライアント連携・tool-calling ガイド

> 最終更新: 2026-07-03

open-context は「リモート(Streamable HTTP)+ カスタムヘッダー」対応の MCP クライアントなら動作する。ただし **クライアントがツールを実際に発火できるか(tool-calling)** は、MCP サーバー側ではなく **モデルとランタイムの組み合わせ** に強く依存する。本ドキュメントは実機検証で得た知見をまとめる。

接続設定そのもの(各クライアントの config)は [README](../../../README.md) / [README_ja](../../../README_ja.md) の Quickstart を参照。

---

## 1. 大原則: tool-calling 成否はモデルが8割

open-context への接続が `connected` でも、モデルが正しい **構造化 tool_call** を出せなければツールは発火しない。まずモデルを選ぶ。

| モデル | tool-calling | 備考 |
|---|---|---|
| Claude / GPT 系 | ◎ 確実 | 実運用の本命(要 API キー) |
| `opencode/nemotron-3-ultra-free` | ◎ 確実 | 無料・高速。検証で `get_readme`/`list_contexts` 発火を確認 |
| `google/gemini-2.5-flash` | ✕ 空応答 | MCP ツールのスキーマを厳格判定で弾き、応答が空になる |
| ローカル 7B/8B | △〜✕ | ランタイム依存(下記)。ツール名を明示すれば発火率は上がる |

---

## 2. ローカルランタイムの差 (Ollama vs LM Studio)

同じモデルでもランタイムで挙動が変わる。`/v1/chat/completions`(OpenAI 互換)への同一リクエストで検証:

| ランタイム × モデル | 構造化 tool_calls | 実挙動 |
|---|---|---|
| Ollama × `qwen2.5-coder:7b` | ✕ | tool call を **テキスト**で返す(テンプレート起因)。ツールは発火しない |
| Ollama × `qwen3:8b` | ◎ | 構造化 tool_calls を返す。ただし thinking で低速 |
| LM Studio × `qwen2.5-coder-7b-instruct`(MLX) | ◎ | LM Studio がモデルのツール出力を構造化 tool_calls に**パース**するため発火する |

**結論**: ローカルで `qwen2.5-coder` を使うなら **LM Studio**。Ollama を使うなら **`qwen3`**。LM Studio + qwen2.5-coder-7b(MLX)+ open-context で `get_readme` の版指定取得まで実機確認済み。

### 2.1 ローカルモデル比較（16GB クラス・実機検証）

| モデル | tool-calling | 特徴 | ネイティブ最大コンテキスト |
|---|---|---|---|
| `qwen2.5-coder-7b-instruct`(MLX 8bit) | ◎ 即発火 | 軽快・省メモリ・素直。コード補完寄り | 32,768 (32K)※rope_scaling 無効ビルド。YaRN で 128K 拡張可 |
| `nvidia Nemotron-Nano-12B-v2`(GGUF) | ◎ 発火 | 出力品質・要約・多言語が上。ただし推論モデルで冗長・やや重い | 1,048,576 (1M)※メタデータ値 |

- **コンテキストは入力/出力で共有**する 1 つの窓(別枠ではない)。加えて生成上限(max tokens)を別途設定できる。
- LM Studio は既定で **8,192** でロードする(ロード時に引き上げ可)。ただし窓を広げるほど KV キャッシュで RAM を消費するため、**16GB では実用上 8K〜32K 程度**。Nemotron の 1M はメタデータ上の値で 16GB では載らない。

### 2.2 推論モデルは `/no_think` にする

Nemotron-Nano のような**推論(thinking)モデル**は、単純なツール呼び出しでも大量に思考して遅く・冗長になる。加えて必須引数(`get_readme` の `version` 等)が欠けると「捏造せず聞き返す」律儀な挙動で止まりがち。対策:

- システムプロンプト(または最初のメッセージ)に **`/no_think`** を入れて思考を切る
- 多言語モデルは言語ドリフト(中国語化 等)することがあるので **`必ず日本語で回答してください`** 等を併記する

推奨システムプロンプト例:

```
/no_think
必ず日本語で回答してください。
```

非推論モデル(`qwen2.5-coder`)は素直に即発火するため、この対策は不要。**単純なツール用途では非推論モデルが快適、複雑な計画では推論モデル**という住み分け。

### 2.3 `version` はプロジェクト文脈が前提

open-context のツールは `version`(実インストール版・semver レンジ不可)を要求する。これは **lockfile / `node_modules` を読めるコーディングエージェント**での利用を想定した設計。素の LLM チャット(プロジェクト無し)では版のソースが無いため、律儀なモデルは版を尋ねて止まる。素チャットで試すときは `react@18.2.0` のように**版を明示**するか、`latest` を許容するプロンプトにする。

---

## 3. OpenCode の tool-calling を安定させる

### 3.1 権限ブロックに注意

headless の `opencode run` は権限で**黙ってブロック**され、ツール未実行のまま空応答になることがある。回避策は2つ:

- `--auto` フラグ: 明示的に deny されていない全操作を自動承認(手軽だが乱暴)
- `permission` 設定: ツールは許可しつつ危険操作だけ `ask`/`deny`(推奨)

```json
{
  "permission": {
    "*": "allow",
    "bash": { "*": "allow", "rm *": "ask", "git push *": "ask" }
  }
}
```

`permission` は「最後にマッチしたルールが勝つ」ワイルドカード方式。`.env` は既定 deny、`external_directory`/`doom_loop` は既定 `ask`。TUI は都度プロンプトで承認できるため、この設定は主に headless 向け。

### 3.2 MCP ツールの命名

MCP ツールはモデルへ **`<server>_<tool>`** 名で渡る(例: `open-context_get_readme`)。弱いモデルにはこの正式名を**明示**すると発火率が上がる。

### 3.3 カスタムプロバイダは `tools: true`

OpenAI 互換のカスタムプロバイダ(ローカル LLM 等)は、モデル定義に `"tools": true` を付けないとツールが渡らない。

### 3.4 推奨 config (`~/.config/opencode/opencode.json`)

```json
{
  "$schema": "https://opencode.ai/config.json",
  "permission": {
    "*": "allow",
    "bash": { "*": "allow", "rm *": "ask", "git push *": "ask" }
  },
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

利用時は tool-calling 対応モデル(`nemotron-3-ultra-free` か Claude/GPT)を選ぶ。

---

## 4. 切り分けの手順

ツールが発火しない時は上流から順に確認する。

1. **接続**: クライアントの MCP 一覧が `connected` か
2. **供給**: モデルへのリクエストに open-context ツールが含まれるか(OpenAI 互換なら `/v1` へのリクエストの `tools` 配列を傍受して確認)
3. **構造化**: モデルが `tool_calls`(構造化)を返すか、テキストで返すか(§2 の切り分け)
4. **権限**: ツール実行が権限でブロックされていないか(§3.1)

サーバー単体の疎通は、LLM を介さず MCP プロトコルを直接叩けば数秒で確認できる(`initialize` → `tools/list` → `tools/call list_contexts`)。
