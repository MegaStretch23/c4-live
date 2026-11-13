import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from c4_live import render
from c4_live.cli import main
from c4_live.diff import diff_models, scan_ref, to_markdown
from c4_live.scan import scan, ts_specifiers

FIX = Path(__file__).parent / "fixtures"


def rels(m):
    return {(r.src, r.dst) for r in m.relations}


def test_python_scan_containers_components_relations():
    m = scan(FIX / "py_repo", name="py_repo")
    assert {c.id for c in m.containers} == {"billing", "root-modules", "shop"}
    ids = {c.id for c in m.components}
    assert {"shop/cart", "shop/prices", "shop/__init__", "billing/invoice", "root-modules/main"} <= ids
    assert ("shop/cart", "shop/prices") in rels(m)            # relative `from . import prices`
    assert ("shop/cart", "billing/invoice") in rels(m)        # absolute from-import
    assert ("billing/invoice", "shop/prices") in rels(m)      # `from shop import prices` resolves to the submodule
    assert ("root-modules/main", "shop/cart") in rels(m)
    assert ("shop/cart", "shop/__init__") not in rels(m)      # `from . import prices` links prices, not the package
    cart = next(c for c in m.components if c.id == "shop/cart")
    assert cart.externals == ["requests"]                      # stdlib json is not external
    assert ("shop", "billing") in m.container_relations() and ("billing", "shop") in m.container_relations()


def test_typescript_scan_workspaces_and_imports():
    m = scan(FIX / "ts_repo", name="ts_repo")
    assert {c.id for c in m.containers} == {"@fx/core", "@fx/web"}
    assert next(c for c in m.containers if c.id == "@fx/web").technology == "npm workspace package"
    r = rels(m)
    app = "@fx/web/packages/web/src/app"
    assert (app, "@fx/web/packages/web/src/types") in r
    assert (app, "@fx/web/packages/web/src/lazy") in r         # dynamic import()
    assert (app, "@fx/web/packages/web/src/legacy") in r       # require(), .js file
    assert (app, "@fx/core/packages/core/src/index") in r      # workspace package -> its entry file
    assert ("@fx/core/packages/core/src/index", "@fx/core/packages/core/src/util") in r   # './util.js' -> util.ts
    assert ("@fx/core/packages/core/src/index", "@fx/core/packages/core/src/math") in r
    assert not any("ghost" in x for pair in r for x in pair)   # commented-out import ignored
    assert m.externals() == ["lodash", "react"]                # 'fs' is a node builtin
    assert not any(c.path.endswith("app.test.ts") for c in m.components)
    assert any(c.path.endswith("app.test.ts") for c in scan(FIX / "ts_repo", include_tests=True).components)


def test_ts_specifiers_forms():
    src = "import a from 'a'; import 'side'; export * from './e'; const x = require('r'); import('d'); // import z from 'z'\n/* import q from 'q' */"
    assert sorted(ts_specifiers(src)) == ["./e", "a", "d", "r", "side"]


def test_scan_is_deterministic():
    assert scan(FIX / "py_repo").to_json() == scan(FIX / "py_repo").to_json()


def test_render_mermaid():
    out = render.mermaid(scan(FIX / "py_repo", name="py_repo"))
    assert "C4Context" in out and "C4Container" in out and out.count("C4Component") == 3
    assert 'System_Ext(ext_requests, "requests"' in out
    assert 'Container(c_shop, "shop", "Python package"' in out
    assert 'Rel(c_shop, c_billing, "imports")' in out
    assert out.count("{") == out.count("}")
    only = render.mermaid(scan(FIX / "py_repo"), "context")
    assert "C4Container" not in only


def test_render_dsl():
    out = render.dsl(scan(FIX / "ts_repo", name="ts_repo"))
    assert out.startswith('workspace "ts_repo" {') and out.count("{") == out.count("}")
    assert 'softwareSystem "lodash"' in out and "include *" in out
    # container relationships come before component ones
    assert out.index("c__fx_web -> c__fx_core") < out.index("m__fx_web_packages_web_src_app -> ")


def git(repo, *a):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, env=env)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "proj"
    shutil.copytree(FIX / "py_repo", r)
    git(r, "init", "-q", "-b", "main")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "base")
    return r


def test_diff_between_refs(repo):
    (repo / "shop" / "tax.py").write_text("import numpy\nfrom . import prices\n")
    (repo / "shop" / "cart.py").write_text("from . import tax\nfrom . import prices\n")
    (repo / "billing" / "invoice.py").write_text("def make_invoice(items):\n    return {}\n")   # drops billing->shop edge
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "change")
    d = diff_models(scan_ref(repo, "HEAD~1"), scan_ref(repo, "HEAD"))
    assert d["changed"]
    assert d["components"]["added"] == ["shop/tax"]
    assert ["billing/invoice", "shop/prices"] in d["relations"]["removed"]
    assert ["shop/cart", "shop/tax"] in d["relations"]["added"]
    assert {"id": "shop/cart", "changes": ["dropped external imports: requests"]} in d["components"]["changed"]
    assert ["billing", "shop"] in d["container_relations"]["removed"]
    md = to_markdown(d, "HEAD~1", "HEAD")
    assert "`shop/tax`" in md and "Relations removed" in md
    # the repo itself was not touched
    assert subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True).stdout == ""


def test_diff_same_ref_and_worktree(repo):
    d = diff_models(scan_ref(repo, "HEAD"), scan_ref(repo, "WORKTREE"))
    assert not d["changed"] and "No architectural change" in to_markdown(d)
    (repo / "extra.py").write_text("import shop\n")
    assert diff_models(scan_ref(repo, "HEAD"), scan_ref(repo, "WORKTREE"))["components"]["added"] == ["root-modules/extra"]


def test_cli_scan_and_diff_exit_codes(repo, capsys, tmp_path):
    assert main(["scan", str(FIX / "py_repo"), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["system"] == "py_repo"
    assert main(["diff", str(repo), "--base", "HEAD", "--head", "WORKTREE", "--fail-on-change"]) == 0
    (repo / "new.py").write_text("import shop\n")
    assert main(["diff", str(repo), "--base", "HEAD", "--head", "WORKTREE", "--fail-on-change"]) == 1
    assert main(["diff", str(repo), "--base", "HEAD", "--head", "WORKTREE"]) == 0       # no flag: report only
    capsys.readouterr()
    assert main(["diff", str(repo), "--base", "nope", "--head", "HEAD"]) == 2
    assert "c4-live:" in capsys.readouterr().err
    out = tmp_path / "m.mmd"
    assert main(["scan", str(FIX / "ts_repo"), "--format", "dsl", "-o", str(out)]) == 0
    assert out.read_text().startswith("workspace")


def test_subdirectory_diff(tmp_path):
    r = tmp_path / "mono"
    shutil.copytree(FIX / "py_repo", r / "services" / "api")
    git(r, "init", "-q", "-b", "main"); git(r, "add", "-A"); git(r, "commit", "-q", "-m", "a")
    (r / "services" / "api" / "z.py").write_text("import shop\n")
    git(r, "add", "-A"); git(r, "commit", "-q", "-m", "b")
    d = diff_models(scan_ref(r / "services" / "api", "HEAD~1"), scan_ref(r / "services" / "api", "HEAD"))
    assert d["components"]["added"] == ["root-modules/z"]
