import unittest

from c4_live.core import build_graph, diff_edges, ts_specs, is_test, wanted

PY = {
    "app/__init__.py": "",
    "app/main.py": "import os\nimport requests\nfrom app import util\nfrom .db import models\nfrom . import config\nimport yaml.loader\n",
    "app/util.py": "from app.config import X\n",
    "app/config.py": "X = 1\n",
    "app/db/__init__.py": "",
    "app/db/models.py": "from ..util import helper\nimport sqlalchemy\n",
    "app/broken.py": "def (:\n",
    "tools/run.py": "import app.main\nfrom app.db.models import Thing\nimport json\n",
}


class PythonTests(unittest.TestCase):
    def setUp(self):
        self.g = build_graph(PY, "demo")

    def test_edges(self):
        e = set(self.g.edges)
        self.assertIn(("app/main.py", "app/util.py"), e)           # from app import util -> submodule
        self.assertIn(("app/main.py", "app/db/models.py"), e)      # relative from .db import models
        self.assertIn(("app/main.py", "app/config.py"), e)         # from . import config
        self.assertIn(("app/util.py", "app/config.py"), e)
        self.assertIn(("app/db/models.py", "app/util.py"), e)      # from ..util import helper (helper is not a module -> util)
        self.assertIn(("tools/run.py", "app/main.py"), e)
        self.assertIn(("tools/run.py", "app/db/models.py"), e)

    def test_external_and_stdlib(self):
        pk = {p for (_, p) in self.g.ext_edges}
        self.assertEqual(pk, {"requests", "yaml", "sqlalchemy"})   # os / json are stdlib, app is internal

    def test_syntax_error_is_reported_not_hidden(self):
        self.assertEqual([p for p, _ in self.g.skipped], ["app/broken.py"])

    def test_units(self):
        self.assertEqual(self.g.unit("app/main.py"), ("app", "app/main"))
        self.assertEqual(self.g.unit("app/db/models.py"), ("app", "app/db"))
        self.assertEqual(self.g.unit("app/__init__.py"), ("app", "app/(package)"))
        self.assertEqual(self.g.unit("tools/run.py"), ("tools", "tools/run"))

    def test_container_aggregate(self):
        internal, ext = self.g.aggregate("container")
        self.assertEqual(internal[("tools", "app")], 2)
        self.assertNotIn(("app", "app"), internal)
        self.assertEqual(ext[("app", "requests")], 1)

    def test_src_layout_and_single_chain_strip(self):
        g = build_graph({"src/pkg/__init__.py": "", "src/pkg/a/x.py": "from pkg.b import y\n", "src/pkg/b/y.py": ""}, "s")
        self.assertEqual(g.strip, ("pkg",))
        self.assertEqual(g.unit("src/pkg/a/x.py"), ("a", "a/x"))
        self.assertIn(("src/pkg/a/x.py", "src/pkg/b/y.py"), g.edges)


TS = {
    "tsconfig.json": '{ // c\n "compilerOptions": { "baseUrl": ".", "paths": { "@lib/*": ["lib/*"] }, }, }',
    "app/page.tsx": "import React from 'react'\nimport { Card } from '@/components/card'\nimport { x } from '@lib/util'\nimport './side.css'\nimport fs from 'node:fs'\nimport p from 'path'\n",
    "components/card.tsx": "import type { A } from '../lib/util'\nexport * from './sub'\nconst z = require('lodash/fp')\n",
    "components/sub/index.ts": "import('@scope/pkg/deep')\n",
    "components/sub.ts": "",
    "lib/util.ts": "// import fake from 'nope'\n/* import x from 'nope2' */\nexport const u = 1\nconst url = 'http://x.com/a'\nimport z from './missing'\n",
}


class TsTests(unittest.TestCase):
    def test_specs(self):
        t = "import a, {\n b,\n c } from \"./m\"\nexport { d } from './n'\nexport * from './o'\nimport './p'\nconst q = require('r')\nawait import('s')\n"
        self.assertEqual(sorted(ts_specs(t)), ["./m", "./n", "./o", "./p", "r", "s"])

    def test_comments_ignored(self):
        self.assertEqual(ts_specs("// import a from 'x'\n/* import b from 'y' */\nimport c from 'z'"), ["z"])

    def test_graph(self):
        g = build_graph(TS, "web")
        e = set(g.edges)
        self.assertIn(("app/page.tsx", "components/card.tsx"), e)       # @/ alias via root fallback
        self.assertIn(("app/page.tsx", "lib/util.ts"), e)               # tsconfig paths
        self.assertIn(("components/card.tsx", "lib/util.ts"), e)        # relative
        self.assertIn(("components/card.tsx", "components/sub.ts"), e)  # file wins over dir index
        pk = {p for (_, p) in g.ext_edges}
        self.assertEqual(pk, {"react", "lodash", "@scope/pkg"})         # node:fs / path / nope skipped, side.css unresolved relative -> not external
        self.assertEqual(g.lang["app/page.tsx"], "TypeScript")

    def test_filters(self):
        self.assertTrue(is_test("tests/a.py") and is_test("src/a.test.ts") and is_test("pkg/test_x.py"))
        self.assertFalse(wanted("node_modules/x/index.js") or wanted("a/types.d.ts") or wanted(".github/x.py"))
        self.assertTrue(wanted("a/b.mjs") and not wanted("a/b.test.ts") and wanted("a/b.test.ts", True))


class DiffTests(unittest.TestCase):
    def test_diff(self):
        a = build_graph({"p/a.py": "import p.b\n", "p/b.py": "", "p/c.py": "import numpy\n"}, "x", strip="")
        b = build_graph({"p/a.py": "import p.c\n", "p/b.py": "", "p/c.py": "import requests\n", "q/n.py": "import p.a\n"}, "x", strip="")
        d = diff_edges(a, b, "component")
        self.assertEqual(d["added"], [("p/a", "p/c"), ("p/c", "ext:requests"), ("q/n", "p/a")])
        self.assertEqual(d["removed"], [("p/a", "p/b"), ("p/c", "ext:numpy")])
        self.assertEqual(d["added_nodes"], ["q/n"])
        self.assertEqual(diff_edges(a, a, "container")["added"], [])


if __name__ == "__main__":
    unittest.main()
