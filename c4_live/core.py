"""Scan a repo's imports into a graph and cluster it into C4 levels (context / container / component).

Python imports come from `ast`. TypeScript / JavaScript imports come from a regex pass (not a compiler), so
dynamic specifiers built at runtime and `paths` aliases beyond the root tsconfig.json are not followed.
The scanner works on {relative posix path: source text}, so the same code reads a directory or a git ref.
"""
from __future__ import annotations

import ast
import io
import json
import os
import posixpath
import re
import subprocess
import sys
import tarfile
from collections import Counter

LANG = {".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript", ".cts": "TypeScript",
        ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript"}
TS_EXTS = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
SKIP_DIRS = {"node_modules", "venv", ".venv", "env", "__pycache__", "dist", "build", "site-packages", "vendor", "coverage",
             "target", ".git", ".tox", ".next", ".eggs"}
TEST_DIRS = {"test", "tests", "__tests__", "testing", "spec", "specs", "e2e"}
MAX_BYTES = 1_000_000
NODE_BUILTINS = {"assert", "buffer", "child_process", "cluster", "console", "constants", "crypto", "dgram", "dns", "domain", "events",
                 "fs", "http", "http2", "https", "inspector", "module", "net", "os", "path", "perf_hooks", "process", "punycode",
                 "querystring", "readline", "repl", "stream", "string_decoder", "timers", "tls", "tty", "url", "util", "v8", "vm",
                 "worker_threads", "zlib"}


def is_test(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1]
    return (any(p in TEST_DIRS for p in parts[:-1]) or name.startswith("test_") or name == "conftest.py"
            or re.search(r"(_test\.py|\.test\.[a-z]+|\.spec\.[a-z]+)$", name) is not None)


def wanted(path: str, include_tests: bool = False) -> bool:
    parts = path.split("/")
    if any(p in SKIP_DIRS or p.startswith(".") for p in parts[:-1]):
        return False
    name = parts[-1]
    if name in ("tsconfig.json", "jsconfig.json") and len(parts) == 1:
        return True
    ext = os.path.splitext(name)[1]
    if ext not in LANG or name.endswith(".d.ts"):
        return False
    return include_tests or not is_test(path)


def files_from_dir(root: str, include_tests: bool = False) -> dict[str, str]:
    out: dict[str, str] = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in SKIP_DIRS and not d.startswith("."))
        for fn in sorted(fns):
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if wanted(rel, include_tests) and os.path.getsize(full) <= MAX_BYTES:
                with open(full, encoding="utf-8", errors="replace") as f:
                    out[rel] = f.read()
    return out


def files_from_ref(repo: str, ref: str, include_tests: bool = False) -> dict[str, str]:
    """Read a git ref with `git archive`, streamed, nothing is checked out."""
    proc = subprocess.Popen(["git", "-C", repo, "archive", "--format=tar", ref], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out: dict[str, str] = {}
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tf:
            for m in tf:
                if m.isfile() and m.size <= MAX_BYTES and wanted(m.name, include_tests):
                    out[m.name] = tf.extractfile(m).read().decode("utf-8", errors="replace")
    except tarfile.TarError:
        pass
    err = proc.stderr.read().decode("utf-8", errors="replace").strip()
    if proc.wait() != 0:
        raise ValueError(f"git archive {ref} failed in {repo}: {err or 'unknown ref'}")
    return out


# ---------------------------------------------------------------- Python

def _py_index(paths: set[str]) -> dict[str, str]:
    """dotted module name -> file. A file is reachable by its full path from the scan root (namespace packages),
    from under a root-level src/, and from the top of its unbroken __init__.py chain (the regular-package case)."""
    init_dirs = {posixpath.dirname(p) for p in paths if p.endswith("/__init__.py")}
    idx: dict[str, list[str]] = {}
    for p in sorted(paths):
        d = p.split("/")[:-1]
        stem = posixpath.basename(p)[:-3]
        top = len(d)
        while top > 0 and "/".join(d[:top]) in init_dirs:
            top -= 1
        starts = {0, top} | ({1} if d[:1] == ["src"] else set())
        for i in starts:
            name = d[i:] + ([] if stem == "__init__" else [stem])
            if name:
                idx.setdefault(".".join(name), []).append(p)
    return {k: sorted(v, key=lambda x: (x.count("/"), x))[0] for k, v in idx.items()}


def _py_mod_file(parts: list[str], paths: set[str]) -> str | None:
    s = "/".join(parts)
    for c in ((s + ".py", s + "/__init__.py") if parts else ("__init__.py",)):
        if c in paths:
            return c
    return None


def _py_imports(path: str, text: str, paths: set[str], idx: dict[str, str], local_tops: set[str]):
    """-> (internal target files, external package names). Raises SyntaxError / ValueError on unparsable source."""
    tree = ast.parse(text)
    internal: list[str] = []
    external: list[str] = []

    def absolute(module: str, names: list[str]):
        parts = module.split(".")
        main = next((idx[".".join(parts[:k])] for k in range(len(parts), 0, -1) if ".".join(parts[:k]) in idx), None)
        got, need_main = [], not names
        for n in names:
            sub = idx.get(module + "." + n)
            if sub:
                got.append(sub)
            else:
                need_main = True
        if need_main and main:
            got.append(main)
        if got:
            internal.extend(got)
        elif parts[0] not in sys.stdlib_module_names and parts[0] not in local_tops:
            external.append(parts[0])

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                absolute(a.name, [])
        elif isinstance(node, ast.ImportFrom):
            names = [a.name for a in node.names if a.name != "*"]
            if node.level == 0 and node.module:
                absolute(node.module, names)
            elif node.level > 0:
                d = posixpath.dirname(path).split("/") if "/" in path else []
                if node.level - 1 > len(d):
                    continue
                base = d[:len(d) - (node.level - 1)] + (node.module.split(".") if node.module else [])
                main = _py_mod_file(base, paths)
                need_main = not names or any(a.name == "*" for a in node.names)
                for n in names:
                    sub = _py_mod_file(base + [n], paths)
                    if sub:
                        internal.append(sub)
                    else:
                        need_main = True
                if need_main and main:
                    internal.append(main)
    return internal, external


# ---------------------------------------------------------------- TypeScript / JavaScript

_FROM = re.compile(r"""(?:^|[;\s}])(?:import|export)\b[^'"`;]*?\bfrom\s*(['"])([^'"\n]+)\1""")
_BARE = re.compile(r"""(?:^|[;\s}])import\s*(['"])([^'"\n]+)\1""")
_CALL = re.compile(r"""\b(?:require|import)\s*\(\s*(['"])([^'"\n]+)\1\s*\)""")
_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_LINE = re.compile(r"(?m)(?<![:\w'\"`])//.*$")


def ts_specs(text: str) -> list[str]:
    text = _LINE.sub("", _BLOCK.sub("", text))
    return [m.group(2) for rx in (_FROM, _BARE, _CALL) for m in rx.finditer(text)]


def _ts_candidates(base: str) -> list[str]:
    root, ext = posixpath.splitext(base)
    c = [base]
    if ext in (".js", ".jsx", ".mjs", ".cjs"):
        c += [root + e for e in (".ts", ".tsx", ".mts", ".cts")]
    return c + [base + e for e in TS_EXTS] + [base + "/index" + e for e in TS_EXTS]


def _tsconfig(files: dict[str, str]):
    for name in ("tsconfig.json", "jsconfig.json"):
        if name in files:
            t = _LINE.sub("", _BLOCK.sub("", files[name]))
            t = re.sub(r",(\s*[}\]])", r"\1", t)
            try:
                co = json.loads(t).get("compilerOptions", {})
                return posixpath.normpath(co.get("baseUrl", ".")) if co.get("baseUrl") else None, co.get("paths", {}) or {}
            except (ValueError, AttributeError):
                return None, {}
    return None, {}


def _ts_resolve(spec: str, frm: str, paths: set[str], base_url, aliases) -> str | None:
    bases: list[str] = []
    if spec.startswith("."):
        bases.append(posixpath.normpath(posixpath.join(posixpath.dirname(frm), spec)))
    else:
        for pat, targets in aliases.items():
            if pat.endswith("*") and spec.startswith(pat[:-1]):
                rest = spec[len(pat) - 1:]
                bases += [posixpath.normpath(posixpath.join(base_url or ".", t.replace("*", rest))) for t in targets]
            elif pat == spec:
                bases += [posixpath.normpath(posixpath.join(base_url or ".", t)) for t in targets]
        if base_url is not None:
            bases.append(posixpath.normpath(posixpath.join(base_url, spec)))
        if spec.startswith(("@/", "~/")):
            bases += [spec[2:], "src/" + spec[2:]]
    for b in bases:
        if b.startswith(".."):
            continue
        for c in _ts_candidates(b):
            if c in paths:
                return c
    return None


def _ts_external(spec: str) -> str | None:
    if spec.startswith((".", "/")) or spec.startswith("node:") or spec.startswith("data:"):
        return None
    parts = spec.split("/")
    name = "/".join(parts[:2]) if spec.startswith("@") and len(parts) > 1 else parts[0]
    return None if name in NODE_BUILTINS else name


# ---------------------------------------------------------------- graph + C4 clustering

class Graph:
    def __init__(self, name: str = "system"):
        self.name = name
        self.lang: dict[str, str] = {}          # file -> language
        self.edges: Counter = Counter()         # (file, file) -> import statements
        self.ext_edges: Counter = Counter()     # (file, package) -> import statements
        self.skipped: list[tuple[str, str]] = []
        self.strip: tuple[str, ...] = ()

    # the (container, component) a file belongs to
    def _parts(self, path: str) -> list[str]:
        parts = path.split("/")
        if parts[0] == "src" and len(parts) > 1:
            parts = parts[1:]
        n = len(self.strip)
        if n and tuple(parts[:n]) == self.strip and len(parts) > n:
            parts = parts[n:]
        return parts

    def unit(self, path: str) -> tuple[str, str]:
        parts = self._parts(path)
        stem = lambda s: "(package)" if os.path.splitext(s)[0] in ("__init__", "index") else os.path.splitext(s)[0]
        if len(parts) == 1:
            return "(root)", "(root)/" + stem(parts[0])
        container = parts[0]
        return container, container + "/" + (stem(parts[1]) if len(parts) == 2 else parts[1])

    def node(self, path: str, level: str) -> str:
        return {"module": lambda: path, "component": lambda: self.unit(path)[1], "container": lambda: self.unit(path)[0]}[level]()

    def aggregate(self, level: str) -> tuple[Counter, Counter]:
        """-> (internal edges Counter[(a, b)], external edges Counter[(a, package)]) at module/component/container level."""
        a: Counter = Counter()
        for (s, d), n in self.edges.items():
            x, y = self.node(s, level), self.node(d, level)
            if x != y:
                a[(x, y)] += n
        e: Counter = Counter()
        for (s, p), n in self.ext_edges.items():
            e[(self.node(s, level), p)] += n
        return a, e

    def files_of(self, level: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for f in sorted(self.lang):
            out.setdefault(self.node(f, level), []).append(f)
        return out

    def tech(self, files: list[str]) -> str:
        return ", ".join(sorted({self.lang[f] for f in files}))


def _auto_strip(paths: list[str]) -> tuple[str, ...]:
    norm = [p.split("/")[1:] if p.startswith("src/") and p.count("/") else p.split("/") for p in paths]
    prefix: list[str] = []
    while norm:
        n = len(prefix)
        here = [p for p in norm if p[:n] == prefix]
        if any(len(p) == n + 1 for p in here):
            break
        kids = {p[n] for p in here}
        if len(kids) != 1:
            break
        prefix.append(kids.pop())
    return tuple(prefix)


def build_graph(files: dict[str, str], name: str = "system", strip: str | None = None) -> Graph:
    g = Graph(name)
    srcs = {p: t for p, t in files.items() if os.path.splitext(p)[1] in LANG}
    for p in srcs:
        g.lang[p] = LANG[os.path.splitext(p)[1]]
    g.strip = tuple(x for x in strip.strip("/").split("/") if x) if strip is not None else _auto_strip(sorted(srcs))

    py = {p for p in srcs if p.endswith(".py")}
    idx = _py_index(py)
    local_tops = {p.split("/")[0] for p in py} | {p.split("/")[1] for p in py if p.startswith("src/") and p.count("/") > 1}
    local_tops |= {os.path.splitext(t)[0] for t in local_tops}
    for p in sorted(py):
        try:
            internal, external = _py_imports(p, srcs[p], py, idx, local_tops)
        except (SyntaxError, ValueError) as e:
            g.skipped.append((p, f"{type(e).__name__}: {str(e)[:60]}"))
            continue
        for t in internal:
            if t != p:
                g.edges[(p, t)] += 1
        for x in external:
            g.ext_edges[(p, x)] += 1

    ts = {p for p in srcs if not p.endswith(".py")}
    base_url, aliases = _tsconfig(files)
    for p in sorted(ts):
        for spec in ts_specs(srcs[p]):
            t = _ts_resolve(spec, p, ts, base_url, aliases)
            if t:
                if t != p:
                    g.edges[(p, t)] += 1
            else:
                x = _ts_external(spec)
                if x:
                    g.ext_edges[(p, x)] += 1
    return g


def scan_dir(path: str, include_tests: bool = False, strip: str | None = None) -> Graph:
    path = os.path.abspath(path)
    return build_graph(files_from_dir(path, include_tests), os.path.basename(path.rstrip("/")) or "system", strip)


def scan_ref(repo: str, ref: str, include_tests: bool = False, strip: str | None = None) -> Graph:
    repo = os.path.abspath(repo)
    return build_graph(files_from_ref(repo, ref, include_tests), os.path.basename(repo.rstrip("/")) or "system", strip)


def diff_edges(a: Graph, b: Graph, level: str) -> dict:
    """Edges and nodes added / removed between two graphs at one level. Externals appear as 'ext:<package>'."""
    def flat(g: Graph):
        i, e = g.aggregate(level)
        edges = {k: n for k, n in i.items()}
        edges.update({(s, "ext:" + p): n for (s, p), n in e.items()})
        return edges, set(g.files_of(level))
    ea, na = flat(a)
    eb, nb = flat(b)
    return {"added": sorted(set(eb) - set(ea)), "removed": sorted(set(ea) - set(eb)),
            "added_nodes": sorted(nb - na), "removed_nodes": sorted(na - nb),
            "weights_a": ea, "weights_b": eb}
