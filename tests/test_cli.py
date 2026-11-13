import os
import subprocess
import tempfile
import unittest

from c4_live.cli import main
from c4_live.core import build_graph
from c4_live.render import graph_view, mermaid, plantuml, diff_view, diff_text


def sh(cwd, *a):
    subprocess.run(a, cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"})


class RenderTests(unittest.TestCase):
    G = build_graph({"app/a.py": "import requests\nfrom app import b\n", "app/b.py": "", "lib/c.py": "import app.a\n"}, "demo")

    def test_mermaid_levels(self):
        for lvl, head in (("context", "C4Context"), ("container", "C4Container"), ("component", "C4Component")):
            m = mermaid(graph_view(self.G, lvl))
            self.assertTrue(m.startswith(head + "\n"), lvl)
        c = mermaid(graph_view(self.G, "container"))
        self.assertIn('Container(app, "app", "Python", "2 files")', c)
        self.assertIn('Rel(lib, app, "imports (1)")', c)
        self.assertIn('System_Ext(ext_requests, "requests"', c)
        comp = mermaid(graph_view(self.G, "component"))
        self.assertIn('Container_Boundary(grp_app, "app") {', comp)

    def test_plantuml(self):
        p = plantuml(graph_view(self.G, "container"))
        self.assertTrue(p.startswith("@startuml") and p.rstrip().endswith("@enduml"))
        self.assertIn("C4_Container.puml", p)

    def test_container_filter_and_error(self):
        v = graph_view(self.G, "component", "lib")
        self.assertIn("app/a", v.nodes)                       # neighbour pulled in
        with self.assertRaises(ValueError):
            graph_view(self.G, "component", "nope")

    def test_diff_view_colours(self):
        b = build_graph({"app/a.py": "from app import b\n", "app/b.py": "import numpy\n", "lib/c.py": "import app.a\n"}, "demo")
        m = mermaid(diff_view(self.G, b, "component", "A", "B"))
        self.assertIn('UpdateRelStyle(app_b, ext_numpy, $textColor="green"', m)
        self.assertIn('UpdateRelStyle(app_a, ext_requests, $textColor="red"', m)
        self.assertIn("- app/a -> ext:requests", diff_text(self.G, b, "component", "A", "B"))


class GitDiffCli(unittest.TestCase):
    def test_diff_two_refs(self):
        with tempfile.TemporaryDirectory() as d:
            sh(d, "git", "init", "-q", "-b", "main")
            os.makedirs(os.path.join(d, "svc"))
            open(os.path.join(d, "svc", "a.py"), "w").write("import svc.b\n")
            open(os.path.join(d, "svc", "b.py"), "w").write("")
            open(os.path.join(d, "svc", "c.py"), "w").write("")
            sh(d, "git", "add", "-A"); sh(d, "git", "commit", "-qm", "one"); sh(d, "git", "tag", "v1")
            open(os.path.join(d, "svc", "a.py"), "w").write("import svc.c\nimport httpx\n")
            sh(d, "git", "commit", "-qam", "two"); sh(d, "git", "tag", "v2")
            out = os.path.join(d, "out.txt")
            self.assertEqual(main(["diff", "v1", "v2", "--repo", d, "--strip", "", "-o", out]), 0)
            t = open(out).read()
            self.assertIn("+ svc/a -> svc/c", t); self.assertIn("+ svc/a -> ext:httpx", t); self.assertIn("- svc/a -> svc/b", t)
            self.assertIn("2 edge(s) added, 1 removed", t)
            self.assertEqual(main(["diff", "v1", "nope", "--repo", d]), 2)     # bad ref: error, not "no changes"

    def test_scan_writes_file(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "m.py"), "w").write("import requests\n")
            out = os.path.join(d, "o.mmd")
            self.assertEqual(main(["scan", d, "--level", "context", "-o", out]), 0)
            self.assertIn("C4Context", open(out).read())


if __name__ == "__main__":
    unittest.main()
