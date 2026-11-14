import json

from c4diff import cli, graph, render, scanner
from c4diff.scanner import js_imports, strip_js_comments


def edges(sc):
    return set(sc.edges)


def test_python_absolute_relative_and_package_imports(py_repo):
    sc = scanner.scan(py_repo)
    e = edges(sc)
    assert ("app/main.py", "app/models.py") in e          # from app import models (submodule)
    assert ("app/main.py", "app/services/billing.py") in e  # from .services import billing
    assert ("app/models.py", "app/db/session.py") in e    # from app.db import session
    assert ("app/services/billing.py", "app/db/session.py") in e   # relative ..db.session
    assert ("app/services/billing.py", "app/models.py") in e       # `X` is an attribute: falls back to the module
    assert ("tools/gen.py", "app/main.py") in e           # import app.main


def test_python_externals_skip_stdlib_and_syntax_errors_are_reported(py_repo):
    sc = scanner.scan(py_repo)
    assert sc.externals["app/main.py"] == {"requests"}      # os is stdlib, not listed
    assert "app/db/session.py" not in sc.externals           # sqlite3 is stdlib
    assert [s[0] for s in sc.skipped] == ["bad.py"] and "syntax error" in sc.skipped[0][1]


def test_js_import_forms_and_comments():
    src = """
    import a from './a'; import {b} from "./b"
    export * from './c'
    import './side'
    const d = require('./d'); const e = await import('./e')
    // import x from './no1'
    /* import y from './no2' */
    import type { T } from './types'
    """
    assert sorted(js_imports(src)) == sorted(["./a", "./b", "./c", "./side", "./d", "./e", "./types"])
    assert "no1" not in strip_js_comments(src) and strip_js_comments(src).count("\n") == src.count("\n")


def test_typescript_resolution_alias_esm_extension_and_node_modules_skipped(ts_repo):
    sc = scanner.scan(ts_repo)
    assert not any(f.startswith("node_modules") for f in sc.files)
    e = edges(sc)
    assert ("src/index.ts", "src/lib/a.ts") in e
    assert ("src/index.ts", "src/lib/b.ts") in e           # './lib/b.js' really is b.ts
    assert ("src/lib/a.ts", "src/util/x.ts") in e          # tsconfig paths alias, JSON with comment + trailing comma
    assert ("src/lib/a.ts", "src/lib/b.ts") in e           # require
    assert ("src/lib/b.ts", "src/util/x.ts") in e          # dynamic import
    assert ("web/page.tsx", "src/lib/a.ts") in e
    assert sc.externals["src/index.ts"] == {"side-effect-pkg", "react"}
    assert sc.externals["src/util/x.ts"] == {"@scope/pkg"}


def test_clustering_depths_and_layout_dir(ts_repo):
    sc = scanner.scan(ts_repo)
    g2 = graph.build(sc, 2, "ts")
    assert {c["id"] for c in g2["containers"]} == {"src", "lib", "util", "web"}   # src/index.ts stays in "src": nothing is left after stripping
    ids = {c["id"] for c in g2["components"]}
    assert "lib/a" in ids and "util/x" in ids and "web/page" in ids      # src/ is a layout dir and is skipped
    g1 = graph.build(sc, 1, "ts")
    assert g1["components"] == []
    assert {"from": "lib", "to": "util", "weight": 2} in g1["edges"]      # a->x and b->x, distinct file pairs
    assert g1["externals"]["util"] == ["@scope/pkg"]


def test_graph_json_has_no_absolute_paths(py_repo):
    g = graph.build(scanner.scan(py_repo), 2, "py")
    assert py_repo not in json.dumps(g)


def test_mermaid_is_well_formed(py_repo):
    g = graph.build(scanner.scan(py_repo), 2, "my \"repo\"")
    m = render.mermaid(g)
    assert m.startswith("C4Component\n") and "title my 'repo'" in m
    assert m.count("{") == m.count("}") == m.count("Container_Boundary(")
    for line in m.splitlines():
        if line.strip().startswith(("Component(", "Rel(")):
            assert line.count('"') % 2 == 0
    g1 = graph.build(scanner.scan(py_repo), 1, "py")
    m1 = render.mermaid(g1, externals=True)
    assert m1.startswith("C4Container\n") and 'System_Ext(x_requests, "requests"' in m1


def test_diff_between_directories(tmp_path):
    from conftest import write
    a = write(tmp_path / "a", {"p/x.py": "from p import y\n", "p/y.py": "", "p/z.py": ""})
    b = write(tmp_path / "b", {"p/x.py": "from p import y, z\n", "p/y.py": "", "p/z.py": "", "p/w.py": "from p import x\n"})
    d = graph.diff(graph.build(scanner.scan(a), 2), graph.build(scanner.scan(b), 2))
    assert d["nodes_added"] == ["p/w"] and d["nodes_removed"] == []
    assert d["edges_added"] == [{"from": "p/w", "to": "p/x", "weight": 1}, {"from": "p/x", "to": "p/z", "weight": 1}]
    assert d["edges_removed"] == [] and d["edges_changed"] == []
    assert graph.has_changes(d) and not graph.has_changes(graph.diff(graph.build(scanner.scan(a)), graph.build(scanner.scan(a))))


def test_diff_changed_weight_and_removed_edges():
    mk = lambda ed: {"depth": 1, "containers": [{"id": k, "files": 1, "languages": ["python"]} for k in "abc"], "components": [], "edges": ed}
    a = mk([{"from": "a", "to": "b", "weight": 1}, {"from": "a", "to": "c", "weight": 4}])
    b = mk([{"from": "a", "to": "b", "weight": 3}])
    d = graph.diff(a, b)
    assert d["edges_changed"] == [{"from": "a", "to": "b", "before": 1, "after": 3}]
    assert d["edges_removed"] == [{"from": "a", "to": "c", "weight": 4}]
    m = render.mermaid(render.union(a, b), "t", d=d)
    assert '"- imports (was 4 files)"' in m and '"~ imports (1 -> 3 files)"' in m and "UpdateRelStyle(n_a, n_c" in m


def test_cli_diff_git_refs_mermaid_and_exit_code(git_repo, capsys):
    rc = cli.main(["diff", "v1", "v2", "--repo", git_repo, "--format", "mermaid", "--exit-code"])
    out = capsys.readouterr().out
    assert rc == 1
    assert 'UpdateElementStyle(n_pkg_d, $bgColor="#2e7d32"' in out     # added node
    assert '"+ imports (1 file)"' in out
    rc = cli.main(["diff", "v1", "v1", "--repo", git_repo, "--exit-code"])
    assert rc == 0 and "edges added (0)" in capsys.readouterr().out


def test_cli_errors_are_loud(tmp_path, capsys):
    assert cli.main(["graph", str(tmp_path)]) == 2
    assert "no Python or TypeScript" in capsys.readouterr().err
    assert cli.main(["diff", "--repo", str(tmp_path), "--", "-evil", "main"]) == 2
    assert "FAILED" in capsys.readouterr().err


def test_cli_graph_json_and_exclude(py_repo, capsys):
    assert cli.main(["graph", py_repo, "--format", "json", "--exclude", "tools/*", "--exclude", "bad.py"]) == 0
    g = json.loads(capsys.readouterr().out)
    assert g["stats"]["files"] == 7 and all(c["id"] != "tools" for c in g["containers"])
