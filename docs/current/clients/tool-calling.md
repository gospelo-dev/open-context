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
