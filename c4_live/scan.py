"""Scan a source tree into a C4 Model.

Python: `ast` (imports); top-level package dir = container, module file = component.
TypeScript/JavaScript: regex import parser (no tree-sitter); nearest package.json dir = container
(npm workspaces included), module file = component. The regex parser is approximate: it reads static
`import ... from`, `export ... from`, `import()` and `require()` with string literals only.
"""
from __future__ import annotations

import ast
import fnmatch
import json
import posixpath
import re
import sys
from pathlib import Path

from .model import Component, Container, Model, Relation

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "env", "__pycache__", "dist", "build", ".tox", ".mypy_cache",
             ".pytest_cache", ".next", "coverage", ".eggs", "site-packages", ".idea", ".vscode"}
TEST_DIRS = {"tests", "test", "__tests__", "spec", "e2e"}
TS_EXT = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
NODE_BUILTINS = {"fs", "path", "os", "http", "https", "url", "util", "crypto", "stream", "events", "child_process",
                 "assert", "buffer", "zlib", "net", "tls", "dns", "readline", "process", "module", "worker_threads",
                 "querystring", "timers", "vm", "cluster", "perf_hooks", "string_decoder", "tty", "v8", "constants"}


def _is_test_file(name: str) -> bool:
    return (name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"
            or re.search(r"\.(test|spec)\.[a-z]+$", name) is not None)


def _walk(root: Path, include_tests: bool):
    """Yield (relpath posix, Path) for source files under root, honouring skip rules."""
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        parts = rel.parts
        if any(x in SKIP_DIRS or x.endswith(".egg-info") for x in parts[:-1]):
            continue
        if not include_tests and (any(x in TEST_DIRS for x in parts[:-1]) or _is_test_file(parts[-1])):
            continue
        yield rel.as_posix(), p


# ---------------------------------------------------------------- Python

def _py_modules(files: list[tuple[str, Path]]) -> dict[str, tuple[str, Path, str]]:
    """dotted module name -> (relpath, Path, container name). Uses `src/` as import root when present."""
    use_src = any(r.startswith("src/") and r.count("/") >= 2 for r, _ in files)
    mods: dict[str, tuple[str, Path, str]] = {}
    for rel, p in files:
        if not rel.endswith(".py"):
            continue
        base = rel
        if use_src and rel.startswith("src/"):
            base = rel[4:]
        elif use_src and not rel.startswith("src/") and "/" not in rel:
            pass
        parts = base[:-3].split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        dotted = ".".join(parts)
        container = parts[0] if len(base.split("/")) > 1 else "root-modules"
        mods[dotted] = (rel, p, container)
    return mods


def _resolve_py(mods: dict, name: str) -> str | None:
    """Longest dotted prefix of `name` that is a known module."""
    parts = name.split(".")
    while parts:
        cand = ".".join(parts)
        if cand in mods:
            return cand
        parts.pop()
    return None


def _scan_python(root: Path, files, model: Model, cid_of: dict) -> list[tuple[str, str]]:
    mods = _py_modules(files)
    if not mods:
        return []
    top_names = {m.split(".")[0] for m in mods}
    def short(dotted: str, cont: str) -> str:
        if cont != "root-modules" and dotted == cont:
            return "__init__"
        return dotted[len(cont) + 1:] if cont != "root-modules" else dotted

    for dotted, (rel, p, cont) in sorted(mods.items()):
        cid_of[("py", dotted)] = f"{cont}/{short(dotted, cont)}"
    edges: list[tuple[str, str]] = []
    for dotted, (rel, p, cont) in sorted(mods.items()):
        cid = cid_of[("py", dotted)]
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"), filename=rel)
        except (SyntaxError, ValueError) as e:
            model.warnings.append(f"{rel}: not parsed ({type(e).__name__})")
            model.components.append(Component(cid, short(dotted, cont), cont, "Python module", rel))
            continue
        is_pkg = rel.endswith("__init__.py")
        pkg_parts = dotted.split(".") if is_pkg else dotted.split(".")[:-1]
        externals: set[str] = set()
        targets: set[str] = set()
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    up = pkg_parts[: len(pkg_parts) - (node.level - 1)] if node.level - 1 <= len(pkg_parts) else []
                    base = ".".join(up + ([node.module] if node.module else []))
                else:
                    base = node.module or ""
                for al in node.names:
                    sub = f"{base}.{al.name}" if base else al.name
                    # `from pkg import mod` links the submodule; `from pkg import name` links pkg itself
                    names.append(sub if sub in mods else base)
                if node.level:
                    for n in names:
                        t = _resolve_py(mods, n) if n else None
                        if t:
                            targets.add(t)
                    continue
            for n in names:
                if not n:
                    continue
                t = _resolve_py(mods, n)
                if t:
                    targets.add(t)
                else:
                    top = n.split(".")[0]
                    if top and top not in sys.stdlib_module_names and top not in top_names:
                        externals.add(top)
        targets.discard(dotted)
        for t in targets:
            edges.append((cid, cid_of[("py", t)]))
        model.components.append(Component(cid, short(dotted, cont), cont, "Python module", rel, sorted(externals)))
    return edges


# ---------------------------------------------------------------- TypeScript / JavaScript

_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_LINE = re.compile(r"(?m)(^|\s)//.*$")
_IMPORT_PATTERNS = [
    re.compile(r"""\bimport\b[^'";]*?\bfrom\s*['"]([^'"\n]+)['"]"""),
    re.compile(r"""\bimport\s*['"]([^'"\n]+)['"]"""),
    re.compile(r"""\bexport\b[^'";]*?\bfrom\s*['"]([^'"\n]+)['"]"""),
    re.compile(r"""\brequire\(\s*['"]([^'"\n]+)['"]\s*\)"""),
    re.compile(r"""\bimport\(\s*['"]([^'"\n]+)['"]\s*\)"""),
]


def ts_specifiers(src: str) -> list[str]:
    src = _LINE.sub(r"\1", _BLOCK.sub("", src))
    out: list[str] = []
    for pat in _IMPORT_PATTERNS:
        out.extend(pat.findall(src))
    return out


def _load_pkg(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _workspace_globs(pkg: dict) -> list[str]:
    ws = pkg.get("workspaces")
    if isinstance(ws, dict):
        ws = ws.get("packages")
    return [w.strip("/") for w in ws] if isinstance(ws, list) else []


def _scan_ts(root: Path, files, model: Model, cid_of: dict, used_container_ids: set[str]) -> list[tuple[str, str]]:
    ts_files = {rel: p for rel, p in files if rel.endswith(TS_EXT) and not rel.endswith(".d.ts")}
    if not ts_files:
        return []
    pkg_dirs: dict[str, dict] = {}
    for rel, p in files:
        if rel == "package.json" or rel.endswith("/package.json"):
            pkg_dirs[posixpath.dirname(rel) or "."] = _load_pkg(p)
    root_ws = _workspace_globs(pkg_dirs.get(".", {}))

    def container_dir(rel: str) -> str:
        d = posixpath.dirname(rel)
        while True:
            key = d or "."
            if key in pkg_dirs:
                return key
            if not d:
                return ""
            d = posixpath.dirname(d)

    def container_for(rel: str) -> tuple[str, str, str]:
        cdir = container_dir(rel)
        if cdir:
            pkg = pkg_dirs[cdir]
            name = pkg.get("name") or (Path(cdir).name if cdir != "." else root.name)
            is_ws = cdir != "." and any(fnmatch.fnmatch(cdir, g) for g in root_ws)
            return cdir, name, ("npm workspace package" if is_ws else "npm package")
        top = rel.split("/")[0] if "/" in rel else ""
        return (top or "."), (top or "root-modules"), "TypeScript sources"

    comp_of_path: dict[str, str] = {}
    comps: dict[str, tuple[str, Path, str]] = {}
    containers: dict[str, tuple[str, str, str]] = {}
    for rel in sorted(ts_files):
        cdir, cname, tech = container_for(rel)
        containers[cdir] = (cname, tech, cdir)
        mod = re.sub(r"\.[^./]+$", "", rel)
        comp_of_path[rel] = mod
        comps[rel] = (mod, ts_files[rel], cdir)
    # container id uniqueness across languages
    cid_by_dir: dict[str, str] = {}
    for cdir, (cname, tech, _) in sorted(containers.items()):
        cid = cname
        if cid in used_container_ids:
            cid = f"{cname}-ts"
        used_container_ids.add(cid)
        cid_by_dir[cdir] = cid
        model.containers.append(Container(cid, cname, tech, cdir))
    pkg_by_name = {}
    for cdir, pkg in pkg_dirs.items():
        if pkg.get("name") and cdir in cid_by_dir:
            pkg_by_name[pkg["name"]] = cdir
    id_of: dict[str, str] = {}
    for rel, (mod, p, cdir) in comps.items():
        id_of[rel] = f"{cid_by_dir[cdir]}/{mod}"
        cid_of[("ts", rel)] = id_of[rel]

    def find_file(base: str) -> str | None:
        cands = [base]
        stripped = re.sub(r"\.(js|jsx|mjs|cjs)$", "", base)
        if stripped != base:
            cands += [stripped + e for e in (".ts", ".tsx", ".mts", ".cts")]
        cands += [base + e for e in TS_EXT]
        cands += [f"{base}/index{e}" for e in TS_EXT]
        for c in cands:
            if c in ts_files:
                return c
        return None

    def entry_of(cdir: str) -> str | None:
        pkg = pkg_dirs.get(cdir, {})
        prefix = "" if cdir == "." else cdir + "/"
        for key in ("source", "main", "module", "types"):
            v = pkg.get(key)
            if isinstance(v, str):
                t = find_file(posixpath.normpath(prefix + v))
                if t:
                    return t
        for guess in ("src/index", "index", "src/main"):
            t = find_file(prefix + guess)
            if t:
                return t
        return None

    edges: list[tuple[str, str]] = []
    for rel, (mod, p, cdir) in sorted(comps.items()):
        src = p.read_text(encoding="utf-8", errors="replace")
        externals: set[str] = set()
        targets: set[str] = set()
        for spec in ts_specifiers(src):
            if spec.startswith("."):
                t = find_file(posixpath.normpath(posixpath.join(posixpath.dirname(rel), spec)))
                if t and t != rel:
                    targets.add(t)
                continue
            if spec.startswith("node:"):
                continue
            pkgname = "/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0]
            if pkgname in pkg_by_name:
                t = entry_of(pkg_by_name[pkgname])
                if t and t != rel:
                    targets.add(t)
                continue
            if pkgname in NODE_BUILTINS or not pkgname:
                continue
            externals.add(pkgname)
        for t in targets:
            edges.append((id_of[rel], id_of[t]))
        model.components.append(Component(id_of[rel], mod, cid_by_dir[cdir], "TypeScript module", rel, sorted(externals)))
    return edges


# ---------------------------------------------------------------- entry point

def scan(path: str | Path, name: str | None = None, include_tests: bool = False) -> Model:
    root = Path(path).resolve()
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    model = Model(system=name or root.name)
    files = list(_walk(root, include_tests))
    cid_of: dict = {}
    edges = _scan_python(root, files, model, cid_of)
    py_cont = {c.container for c in model.components}
    for cname in sorted(py_cont):
        model.containers.append(Container(cname, cname, "Python package" if cname != "root-modules" else "Python modules",
                                          "." if cname == "root-modules" else cname))
    edges += _scan_ts(root, files, model, cid_of, set(py_cont))
    model.relations = [Relation(a, b) for a, b in edges]
    return model.normalise()
