#!/usr/bin/env python3
"""
Acceptance checker for the deployed gospelo-open-context MCP server.

Deterministic (no LLM): calls the live MCP endpoint for one package@version
and grades it against criteria C1-C5 + H. Prints a JSON verdict.

Usage:
    OPEN_CONTEXT_TEST_TOKEN=ghp_... \
      python quality/acceptance.py <ecosystem> <package> <version> [endpoint]

Verdict: PASS (all green) / WARN (only by-design caveats) / FAIL (broken).
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

DEFAULT_ENDPOINT = "https://open-context.gospelo.dev"
TIMEOUT = 30


def _mcp(endpoint, token, name, arguments):
    """One tools/call. Returns {http, text, isError, latency, error}."""
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }).encode()
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/mcp", data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-GitHub-Token": token,
            # Cloudflare denies the default python-urllib UA (Error 1010).
            "User-Agent": "open-context-quality-loop/1.0",
        },
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = json.loads(r.read().decode("utf-8", "replace"))
            status = r.status
    except urllib.error.HTTPError as e:
        detail = e.read()[:400].decode("utf-8", "replace")
        return {"http": e.code, "text": "", "isError": True, "latency": time.time() - t0, "error": detail}
    except Exception as e:  # timeout, connection, JSON
        return {"http": 0, "text": "", "isError": True, "latency": time.time() - t0, "error": str(e)}
    content = (raw.get("result") or {}).get("content") or []
    text = content[0]["text"] if content else ""
    is_error = bool((raw.get("result") or {}).get("isError"))
    return {"http": status, "text": text, "isError": is_error, "latency": time.time() - t0, "error": None}


def _digits(s):
    return re.sub(r"[^0-9.]", "", s or "")


def _parse_pin(text):
    """First line: '{pkg}@{ver} — {owner}/{repo}[/sub] @ {tag} (sha)'. Return tag."""
    first = (text or "").splitlines()[0] if text else ""
    # take the LAST '@ ... (' so scoped names in the pkg part aren't captured
    m = None
    for m in re.finditer(r"@\s+([^\s(]+)\s*\(", first):
        pass
    return (m.group(1) if m else ""), first


def _tag_version(tag):
    """Version digits from a git tag: 'v1.2.3' / '@scope/pkg@1.2.3' / 'rel_2_0_51'."""
    tail = tag.rsplit("@", 1)[-1]           # drop scoped-name prefix (e.g. @builder.io/qwik@)
    tail = tail[1:] if tail[:1] == "v" else tail
    tail = tail.replace("_", ".")           # SQLAlchemy style: rel_2_0_51 -> rel.2.0.51
    return _digits(tail).strip(".")


def check(endpoint, token, pkg, version, eco):
    crit = []

    def rec(cid, status, detail):
        crit.append({"id": cid, "status": status, "detail": detail})

    # --- get_readme -> C1 (resolve/tag), C2 (readme), H (health) ---
    rd = _mcp(endpoint, token, "get_readme", {"package": pkg, "version": version, "ecosystem": eco})
    if rd["http"] != 200:
        rec("H", "FAIL", f"get_readme HTTP {rd['http']}: {rd.get('error')}")
        rec("C2", "FAIL", "README 取得不可")
        rec("C1", "FAIL", "解決不可")
    else:
        if rd["latency"] > TIMEOUT:
            rec("H", "WARN", f"get_readme 遅延 {rd['latency']:.1f}s")
        tag, header = _parse_pin(rd["text"])
        tag_ok = _tag_version(tag) == version
        if rd["isError"]:
            rec("C1", "FAIL", f"解決エラー: {header[:160]}")
            rec("C2", "FAIL", "README がエラー応答")
        else:
            if tag_ok:
                rec("C1", "PASS", f"tag={tag}")
            elif "default branch" in rd["text"] or "warning" in rd["text"].lower() or "⚠️" in rd["text"]:
                rec("C1", "WARN", f"tag 数字が版と不一致/フォールバック: {header[:160]}")
            else:
                rec("C1", "FAIL", f"tag={tag} が版 {version} と不一致")
            body = rd["text"].split("--- ", 1)[-1]
            rec("C2", "PASS" if len(body) > 50 else "FAIL",
                "README 非空" if len(body) > 50 else "README が空/極小")

    # --- read_files manifest -> C3 (npm version), C5 (file read) ---
    if eco == "npm":
        rf = _mcp(endpoint, token, "read_files", {
            "package": pkg, "version": version, "ecosystem": eco,
            "requests": [{"path": "package.json", "start_line": 1, "end_line": 20}],
        })
        if rf["http"] != 200 or rf["isError"]:
            rec("C5", "FAIL", f"read_files 失敗 HTTP {rf['http']} {rf.get('error') or ''}")
            rec("C3", "FAIL", "package.json 取得不可")
        else:
            rec("C5", "PASS", "package.json 取得")
            m = re.search(r'"version"\s*:\s*"([^"]+)"', rf["text"])
            actual = m.group(1) if m else None
            if actual == version:
                rec("C3", "PASS", f'version={actual}')
            elif actual and _digits(actual) != version and _digits(actual):
                # tag matched requested version but inner package.json differs (monorepo shared tag)
                rec("C3", "WARN", f'package.json version={actual} != {version}(monorepo共有tagの可能性)')
            else:
                rec("C3", "WARN", "package.json version 未検出")
    else:  # pypi: tag match (C1) is the version-precision proof; read README as C5
        rf = _mcp(endpoint, token, "read_files", {
            "package": pkg, "version": version, "ecosystem": eco,
            "requests": [{"path": "README.md", "start_line": 1, "end_line": 3}],
        })
        if rf["http"] == 200 and not rf["isError"] and "Error:" not in rf["text"].split("---", 1)[-1][:40]:
            rec("C5", "PASS", "ファイル取得可")
        else:
            # README path may differ; fall back to trusting C2/get_readme having returned it
            rec("C5", "WARN", "README.md 直読不可(get_readme は成功)")
        rec("C3", "PASS", "PyPI は tag 一致(C1)で版を担保")

    # --- get_documentation_tree scope=docs -> C4 ---
    dt = _mcp(endpoint, token, "get_documentation_tree", {"package": pkg, "version": version, "ecosystem": eco, "scope": "docs"})
    if dt["http"] != 200 or dt["isError"]:
        rec("C4", "FAIL", f"docs tree 失敗 HTTP {dt['http']} {dt.get('error') or ''}")
    else:
        m = re.search(r"(\d+)\s+docs files", dt["text"])
        n = int(m.group(1)) if m else 0
        rec("C4", "PASS" if n >= 1 else "FAIL", f"{n} docs files")

    statuses = [c["status"] for c in crit]
    verdict = "FAIL" if "FAIL" in statuses else ("WARN" if "WARN" in statuses else "PASS")
    return {"package": pkg, "version": version, "ecosystem": eco, "verdict": verdict, "criteria": crit}


def main():
    if len(sys.argv) < 4:
        print("usage: acceptance.py <ecosystem> <package> <version> [endpoint]", file=sys.stderr)
        sys.exit(2)
    eco, pkg, version = sys.argv[1], sys.argv[2], sys.argv[3]
    endpoint = sys.argv[4] if len(sys.argv) > 4 else DEFAULT_ENDPOINT
    token = os.environ.get("OPEN_CONTEXT_TEST_TOKEN", "")
    if not token:
        print("OPEN_CONTEXT_TEST_TOKEN not set", file=sys.stderr)
        sys.exit(2)
    result = check(endpoint, token, pkg, version, eco)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["verdict"] != "FAIL" else 1)


if __name__ == "__main__":
    main()
