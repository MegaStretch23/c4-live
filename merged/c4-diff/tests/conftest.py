import os
import subprocess
import textwrap

import pytest


def write(root, files):
    for rel, body in files.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(body))
    return str(root)


PY_REPO = {
    "app/__init__.py": "",
    "app/main.py": "import os\nfrom app import models\nfrom .services import billing\nimport requests\n",
    "app/models.py": "from app.db import session\n",
    "app/db/__init__.py": "",
    "app/db/session.py": "import sqlite3\n",
    "app/services/__init__.py": "",
    "app/services/billing.py": "from app.models import X\nfrom ..db.session import connect\n",
    "tools/gen.py": "import app.main\n",
    "bad.py": "def (:\n",
}

TS_REPO = {
    "tsconfig.json": '{ // comment\n "compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]},},\n}',
    "src/index.ts": "import { a } from './lib/a';\nexport * from './lib/b.js';\nimport 'side-effect-pkg';\nimport React from 'react';\n",
    "src/lib/a.ts": "import x from '@/util/x';\nconst b = require('./b');\n",
    "src/lib/b.ts": "const m = await import('../util/x');\n// import dead from './nope';\n/* import dead2 from './nope2' */\nconst s = \"import q from './in-a-string-is-ok'\";\n",
    "src/util/x.ts": "import {y} from '@scope/pkg/deep';\nexport const x = 1;\n",
    "web/page.tsx": "import { a } from '../src/lib/a';\n",
    "node_modules/junk/index.js": "require('./a')",
}


@pytest.fixture
def py_repo(tmp_path):
    return write(tmp_path / "py", PY_REPO)


@pytest.fixture
def ts_repo(tmp_path):
    return write(tmp_path / "ts", TS_REPO)


@pytest.fixture
def git_repo(tmp_path):
    r = str(tmp_path / "g")
    write(r, {"pkg/a.py": "from pkg import b\n", "pkg/b.py": "", "pkg/c.py": ""})
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    def git(*a):
        subprocess.run(["git", "-C", r, *a], check=True, capture_output=True, env=env)
    try:
        git("init", "-q"); git("add", "-A"); git("commit", "-qm", "one"); git("tag", "v1")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git unavailable")
    write(r, {"pkg/a.py": "from pkg import b, c\n", "pkg/d.py": "from pkg import a\n"})
    git("add", "-A"); git("commit", "-qm", "two"); git("tag", "v2")
    return r
