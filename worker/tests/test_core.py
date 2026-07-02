"""Unit tests for the pure (non-network) logic. Run under CPython via pytest."""

import github_client
import cache_store
import registry_npm
import version_resolver as vr
import mcp_handler as mh
import chunker
import overrides
import registry_pypi
import auth_resolver


# --- github_client.normalize_repo_url -------------------------------------

def test_normalize_repo_url_variants():
    f = github_client.normalize_repo_url
    assert f("git+https://github.com/vercel/next.js.git") == ("vercel", "next.js")
    assert f("https://github.com/colinhacks/zod") == ("colinhacks", "zod")
    assert f("github:facebook/react") == ("facebook", "react")
    assert f("git://github.com/psf/requests.git") == ("psf", "requests")
    assert f("ssh://git@github.com/expressjs/express.git") == ("expressjs", "express")
    assert f("expressjs/express") == ("expressjs", "express")
    assert f("https://github.com/vercel/next.js/tree/main/packages/next") == ("vercel", "next.js")


def test_normalize_repo_url_rejects_non_github():
    f = github_client.normalize_repo_url
    assert f("https://gitlab.com/foo/bar") is None
    assert f("") is None
    assert f(None) is None


# --- version_resolver._candidate_tags -------------------------------------

def test_candidate_tags_order_and_dedup():
    tags = vr._candidate_tags("15.1.0", "next")
    assert tags[0] == "v15.1.0"
    assert "15.1.0" in tags
    assert "next@15.1.0" in tags
    assert len(tags) == len(set(tags))  # no dups


def test_candidate_tags_scoped_uses_short_name():
    tags = vr._candidate_tags("7.25.0", "@babel/core")
    assert "@babel/core@7.25.0" in tags
    assert "core@7.25.0" in tags  # short (unscoped) variant


def test_digits():
    assert vr._digits("v15.1.0") == "15.1.0"
    assert vr._digits("next@15.1.0") == "15.1.0"


# --- cache_store keys ------------------------------------------------------

def test_cache_keys_encode_scoped():
    assert cache_store.manifest_key("npm", "next", "15.1.0") == "manifests/npm/next/15.1.0.json"
    assert cache_store.manifest_key("npm", "@scope/name", "1.0.0") == "manifests/npm/@scope%2Fname/1.0.0.json"
    assert cache_store.blob_key("abc123") == "blobs/abc123"
    assert cache_store.resolve_key("npm", "@a/b", "2.0.0") == "resolve/npm/@a%2Fb/2.0.0.json"


# --- registry_npm._extract_repo -------------------------------------------

def test_extract_repo_object_with_directory():
    got = registry_npm._extract_repo({
        "repository": {"type": "git", "url": "git+https://github.com/vercel/next.js.git", "directory": "packages/next"}
    })
    assert got == ("vercel", "next.js", "packages/next")


def test_extract_repo_string_form():
    got = registry_npm._extract_repo({"repository": "github:colinhacks/zod"})
    assert got == ("colinhacks", "zod", "")


def test_extract_repo_none_when_missing():
    assert registry_npm._extract_repo({}) is None
    assert registry_npm._extract_repo({"repository": {"url": "https://gitlab.com/x/y"}}) is None


# --- mcp_handler pure helpers ---------------------------------------------

def test_slice_lines():
    text = "\n".join(str(i) for i in range(1, 21))  # "1".."20"
    assert mh._slice_lines(text, 1, 3) == "1\n2\n3"
    assert mh._slice_lines(text, 19, 100).split("\n") == ["19", "20"]  # clamps to end
    assert mh._slice_lines(text, None, None) == text


def test_slice_lines_respects_max_range():
    text = "\n".join(str(i) for i in range(1, 5001))
    out = mh._slice_lines(text, 1, 5000)
    assert len(out.split("\n")) == mh.MAX_LINE_RANGE


def test_pick_readme_prefers_root_md():
    files = {
        "src/build/README.md": {},
        "README.md": {},
        "readme.txt": {},
    }
    assert mh._pick_readme(files) == "README.md"
    assert mh._pick_readme({"docs/guide.md": {}}) is None


def test_content_type_and_doc_detection():
    assert mh._content_type("a.md") == "text/markdown"
    assert mh._content_type("a.d.ts") == "text/plain"
    assert mh._is_doc_path("guide.mdx") is True
    assert mh._is_doc_path("index.ts") is False


def test_grep_candidate_filters():
    assert mh._grep_candidate("src/index.ts") is True
    assert mh._grep_candidate("README.md") is True
    assert mh._grep_candidate("src/foo.py") is True
    # non-text / non-listed extensions excluded
    assert mh._grep_candidate("logo.svg") is False
    assert mh._grep_candidate("image.png") is False
    # vendored / compiled / minified excluded
    assert mh._grep_candidate("dist/index.js") is False
    assert mh._grep_candidate("src/compiled/babel/x.js") is False
    assert mh._grep_candidate("foo.min.js") is False


def test_is_root_doc():
    assert mh._is_root_doc("docs/app/routing.mdx") is True
    assert mh._is_root_doc("README.md") is True
    assert mh._is_root_doc("llms.txt") is True
    assert mh._is_root_doc("llms-full.txt") is True
    assert mh._is_root_doc("docs/logo.svg") is False   # not a doc ext
    assert mh._is_root_doc("src/index.ts") is False     # nested non-docs
    assert mh._is_root_doc("packages/next/readme.md") is False  # nested, not root


def test_resolve_entry_root_vs_subdir():
    manifest = {
        "subdir": "packages/next",
        "files": {"README.md": {"sha": "s1", "size": 1}},
        "root_docs": {"docs/app/routing.mdx": {"sha": "s2", "size": 2}},
    }
    # subdir-relative
    info, full = mh._resolve_entry(manifest, "README.md")
    assert info["sha"] == "s1" and full == "packages/next/README.md"
    # repo-root ('/' prefix)
    info, full = mh._resolve_entry(manifest, "/docs/app/routing.mdx")
    assert info["sha"] == "s2" and full == "docs/app/routing.mdx"
    # missing
    info, full = mh._resolve_entry(manifest, "nope.md")
    assert info is None


def test_chunk_markdown_headings_and_preamble():
    md = "intro line\n\n# Title\ntext\n\n## Sub A\naaa\n\n## Sub B\nbbb"
    secs = chunker.chunk_markdown(md)
    kinds = [(s["kind"], s.get("title"), s["level"]) for s in secs]
    assert kinds[0] == ("preamble", "(preamble)", 0)
    assert ("heading", "Title", 1) in kinds
    assert ("heading", "Sub A", 2) in kinds
    # Sub A spans from its line to just before Sub B
    sub_a = next(s for s in secs if s["title"] == "Sub A")
    sub_b = next(s for s in secs if s["title"] == "Sub B")
    assert sub_a["end_line"] == sub_b["start_line"] - 1


def test_chunk_markdown_ignores_headings_in_code_fence():
    md = "# Real\n```\n# not a heading\n```\n## AlsoReal"
    titles = [s["title"] for s in chunker.chunk_markdown(md)]
    assert "Real" in titles and "AlsoReal" in titles
    assert "not a heading" not in titles


def test_chunk_code_symbols():
    code = (
        "import x\n\n"
        "export function foo() {\n  return 1\n}\n\n"
        "export const bar = 2\n\n"
        "class Baz {\n  method() {}\n}\n"
    )
    secs = chunker.chunk_code(code)
    labels = [(s["kind"], s["title"]) for s in secs]
    assert ("preamble", "(imports/preamble)") in labels
    assert ("function", "foo") in labels
    assert ("const", "bar") in labels
    assert ("class", "Baz") in labels
    # nested method should NOT be a top-level anchor
    assert all(t != "method" for _, t in labels)


def test_chunk_code_python():
    code = "import os\n\ndef alpha():\n    pass\n\nclass Beta:\n    def gamma(self):\n        pass\n"
    labels = [(s["kind"], s["title"]) for s in chunker.chunk_code(code)]
    assert ("def", "alpha") in labels
    assert ("class", "Beta") in labels


def test_chunk_no_structure_returns_empty():
    assert chunker.chunk_markdown("just prose\nno headings") == []
    assert chunker.chunk_code("doThing()\nconsole.log(1)\n// no declarations here") == []


def test_grep_matcher_literal():
    pre, line, err = mh._build_grep_matcher("useRouter", regex=False, ignore_case=False)
    assert err is None
    assert line("const useRouter = ...") is True
    assert line("const userouter = ...") is False  # case-sensitive


def test_grep_matcher_ignore_case():
    pre, line, err = mh._build_grep_matcher("userouter", regex=False, ignore_case=True)
    assert err is None
    assert line("import { useRouter }") is True
    assert pre("... useRouter ...") is True


def test_grep_matcher_regex():
    pre, line, err = mh._build_grep_matcher(r"use[_ ]?router", regex=True, ignore_case=True)
    assert err is None
    assert line("useRouter()") is True
    assert line("use_router()") is True
    assert line("use router()") is True
    assert line("useController()") is False


def test_grep_matcher_invalid_regex():
    pre, line, err = mh._build_grep_matcher("(unclosed", regex=True, ignore_case=False)
    assert line is None and "invalid regex" in err


def test_grep_matcher_query_too_long():
    pre, line, err = mh._build_grep_matcher("x" * (mh.MAX_GREP_QUERY + 1), regex=False, ignore_case=False)
    assert "too long" in err


def test_pypi_extract_repo():
    f = registry_pypi._extract_repo
    # Prefers a Source URL over a readthedocs homepage.
    info = {
        "project_urls": {
            "Documentation": "https://requests.readthedocs.io",
            "Source": "https://github.com/psf/requests",
        },
        "home_page": "https://requests.readthedocs.io",
    }
    assert f(info) == ("psf", "requests")
    # Falls back to home_page when it's a GitHub URL.
    assert f({"home_page": "https://github.com/pallets/flask"}) == ("pallets", "flask")
    # No GitHub anywhere -> None.
    assert f({"project_urls": {"Docs": "https://example.com"}}) is None


def test_candidate_tags_python_style():
    tags = vr._candidate_tags("5.0", "Django")
    assert "Django-5.0" in tags   # python style, no 'v'
    assert "v5.0" in tags
    assert len(tags) == len(set(tags))


def test_overrides_lookup():
    r = overrides.get_override("npm", "react")
    assert r["docs"]["repo"] == "reactjs/react.dev"
    a = overrides.get_override("npm", "astro")
    assert a["docs"]["subdir"] == "src/content/docs"
    ts = overrides.get_override("npm", "typescript")
    assert ts["docs"]["ref"] == "v2"
    assert overrides.get_override("npm", "left-pad") is None
    assert overrides.get_override("pypi", "react") is None


def test_looks_like_github_token():
    f = auth_resolver._looks_like_github_token
    assert f("ghp_abc123") is True
    assert f("github_pat_11ABC") is True
    assert f("gho_x") is True
    assert f("ghs_x") is True
    # our own OAuth-issued opaque tokens are token_urlsafe(32), no gh prefix
    assert f("kJ8nQ2mZ...") is False
    assert f("") is False


def test_contexts_text():
    t = mh._contexts_text()
    assert "npm" in t and "pypi" in t
    assert "npm:react" in t and "reactjs/react.dev" in t
    # Makes clear the override list is not the full set of usable packages.
    assert "not the full set" in t


def test_truncate():
    small = "x" * 10
    assert mh._truncate(small) == small
    big = "y" * (mh.RESPONSE_TRUNCATE + 100)
    out = mh._truncate(big)
    assert "truncated" in out
    assert len(out) < len(big) + 60
