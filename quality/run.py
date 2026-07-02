#!/usr/bin/env python3
"""
Quality loop runner (deterministic, no LLM).

For each monitored package: fetch the latest version, and if it is a MAJOR or
MINOR bump over the recorded baseline, run the acceptance checker against the
live server. PASS/WARN -> advance the baseline. FAIL -> write a Japanese issue
report and leave the baseline unchanged (so it keeps re-alerting until fixed).

Outputs (for GitHub Actions):
  - quality/_reports/{eco}_{pkg}.md   (Japanese issue body, only on FAIL)
  - updates quality/baseline.json     (on PASS/WARN)
  - GITHUB_OUTPUT: has_failures=true|false
"""

import json
import os
import re
import urllib.request

import acceptance  # same directory

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE = os.path.join(HERE, "baseline.json")
REPORTS = os.path.join(HERE, "_reports")


def fetch_latest(eco, pkg):
    if eco == "npm":
        url = f"https://registry.npmjs.org/{pkg.replace('/', '%2F')}"
        with urllib.request.urlopen(url, timeout=30) as r:
            return (json.loads(r.read()).get("dist-tags") or {}).get("latest")
    if eco == "pypi":
        url = f"https://pypi.org/pypi/{pkg}/json"
        with urllib.request.urlopen(url, timeout=30) as r:
            return (json.loads(r.read()).get("info") or {}).get("version")
    return None


def _mm(v):
    nums = re.findall(r"\d+", v or "")
    major = int(nums[0]) if len(nums) > 0 else 0
    minor = int(nums[1]) if len(nums) > 1 else 0
    return major, minor


def is_major_minor_bump(old, new):
    if not new or new == old:
        return False
    om, on = _mm(old)
    nm, nn = _mm(new)
    return (nm > om) or (nm == om and nn > on)


def jp_report(res):
    lines = [
        f"## 品質ループ: `{res['package']}@{res['version']}` ({res['ecosystem']}) が FAIL",
        "",
        "自動品質チェックで、この版のコンテキスト取得に問題が検出されました。",
        "",
        f"- **エンドポイント**: https://open-context.gospelo.dev/mcp",
        f"- **判定**: **{res['verdict']}**",
        "",
        "### 基準ごとの結果",
        "",
        "| 基準 | 結果 | 詳細 |",
        "|---|---|---|",
    ]
    label = {
        "C1": "C1 解決/tag", "C2": "C2 README", "C3": "C3 版一致",
        "C4": "C4 docs一覧", "C5": "C5 ファイル取得", "H": "H 健全性",
    }
    for c in res["criteria"]:
        mark = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(c["status"], c["status"])
        detail = c["detail"].replace("|", "\\|")
        lines.append(f"| {label.get(c['id'], c['id'])} | {mark} | {detail} |")
    lines += [
        "",
        "### 対応",
        "1. ローカルで再現: `OPEN_CONTEXT_TEST_TOKEN=<PAT> python quality/acceptance.py "
        f"{res['ecosystem']} {res['package']} {res['version']}`",
        "2. `worker/src/` を修正し `uv run pytest` と acceptance が緑になることを確認",
        "3. `pywrangler deploy` 後、この Issue を close(次回 cron で自動再検証)",
        "",
        "_このIssueは自動生成です(quality-loop / LLM不使用)。_",
    ]
    return "\n".join(lines)


def main():
    with open(BASELINE, encoding="utf-8") as f:
        cfg = json.load(f)
    endpoint = cfg.get("endpoint", acceptance.DEFAULT_ENDPOINT)
    token = os.environ.get("OPEN_CONTEXT_TEST_TOKEN", "")
    if not token:
        raise SystemExit("OPEN_CONTEXT_TEST_TOKEN not set")

    os.makedirs(REPORTS, exist_ok=True)
    for old in os.listdir(REPORTS):  # clear stale reports
        if old.endswith(".md"):
            os.remove(os.path.join(REPORTS, old))

    any_fail = False
    changed = False
    summary = []
    for p in cfg["packages"]:
        eco, pkg, base = p["ecosystem"], p["package"], p["baseline"]
        try:
            latest = fetch_latest(eco, pkg)
        except Exception as e:
            summary.append(f"- {eco}:{pkg} latest取得失敗: {e}")
            continue
        if not is_major_minor_bump(base, latest):
            summary.append(f"- {eco}:{pkg} 変化なし (baseline {base}, latest {latest})")
            continue
        res = acceptance.check(endpoint, token, pkg, latest, eco)
        summary.append(f"- {eco}:{pkg} {base} -> {latest}: **{res['verdict']}**")
        if res["verdict"] == "FAIL":
            any_fail = True
            with open(os.path.join(REPORTS, f"{eco}_{pkg}.md"), "w", encoding="utf-8") as f:
                f.write(jp_report(res))
        else:
            p["baseline"] = latest  # advance on PASS/WARN
            changed = True

    if changed:
        with open(BASELINE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.write("\n")

    print("=== quality-loop summary ===")
    print("\n".join(summary))

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"has_failures={'true' if any_fail else 'false'}\n")
            f.write(f"baseline_changed={'true' if changed else 'false'}\n")


if __name__ == "__main__":
    main()
