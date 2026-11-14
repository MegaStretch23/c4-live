"""Find source files and the import edges between them (file level)."""
from __future__ import annotations

import ast
import fnmatch
import json
import os
import posixpath
import re
import sys
from dataclasses import dataclass, field

PY_EXT = (".py",)
JS_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env", ".tox", "dist", "build", ".mypy_cache",
             ".pytest_cache", ".next", "site-packages", ".eggs", ".idea", ".vscode"}
MAX_BYTES = 2_000_000
STDLIB = getattr(sys, "stdlib_module_names", frozenset())


@dataclass
class Scan:
    files: dict = field(default_factory=dict)       # rel path -> "python" | "typescript"
    edges: dict = field(default_factory=dict)       # (src rel, dst rel) -> number of import statements
    externals: dict = field(default_factory=dict)   # rel path -> set of external package names
    skipped: list = field(default_factory=list)     # [rel, reason]


def excluded(rel: str, patterns) -> bool:
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, p.rstrip("/") + "/*") for p in patterns)


def collect(root: str, exclude=()) -> dict:
    files = {}
    for dp, dns, fns in os.walk(root, followlinks=False):
        dns[:] = sorted(d for d in dns if d not in SKIP_DIRS and not os.path.islink(os.path.join(dp, d)))
        for fn in sorted(fns):
            full = os.path.join(dp, fn)
            if os.path.islink(full) or fn.endswith(".d.ts"):
                continue
            ext = os.path.splitext(fn)[1]
            lang = "python" if ext in PY_EXT else "typescript" if ext in JS_EXT else None
            if not lang:
                continue
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if not excluded(rel, exclude):
                files[rel] = lang
    return files


# ---------------------------------------------------------------- python

def py_imports(source: str):
    """-> list of (level, module, names) from ast; raises SyntaxError."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            out += [(0, a.name, ()) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            out.append((node.level, node.module or "", tuple(a.name for a in node.names if a.name != "*")))
    return out


def _py_module_file(path: str, files: dict):
    """path like 'a/b/c' -> the file a/b/c.py or a/b/c/__init__.py if scanned."""
    for cand in (path + ".py", (path + "/__init__.py").lstrip("/")):
        if cand in files:
            return cand
    return None


def _py_bases(src: str, files: dict):
    d = posixpath.dirname(src)
    bases = []
    while True:
        bases.append(d)
        if not d:
            break
        d = posixpath.dirname(d)
    if any(f.startswith("src/") for f in files):
        bases.append("src")
    return bases


def _py_lookup(parts, bases, files):
    """Longest prefix of dotted `parts` that is a scanned module under any base. -> (file, n_parts_used) or (None, 0)."""
    for n in range(len(parts), 0, -1):
        for b in bases:
            hit = _py_module_file(posixpath.join(b, *parts[:n]), files)
            if hit:
                return hit, n
    return None, 0


def resolve_py(src: str, level: int, module: str, names, files: dict):
    parts = [p for p in module.split(".") if p]
    if level:
        d = posixpath.dirname(src)
        for _ in range(level - 1):
            d = posixpath.dirname(d)
        bases = [d]
    else:
        bases = _py_bases(src, files)
    hits = []
    if names:  # `from pkg import sub` may import a submodule
        for n in names:
            hit, used = _py_lookup(parts + [n], bases, files)
            if hit and used == len(parts) + 1:
                hits.append(hit)
    if not hits and (parts or level):
        hit, _ = _py_lookup(parts, bases, files) if parts else (_py_module_file(posixpath.join(bases[0]), files), 0)
        if hit:
            hits.append(hit)
    return hits


def external_py(module: str):
    top = module.split(".")[0]
    return top if top and top not in STDLIB else None


# ---------------------------------------------------------------- js / ts

def strip_js_comments(src: str) -> str:
    """Blank out // and /* */ comments (keeping newlines), leaving strings alone."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c in "'\"`":
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == "\\":
                    j += 1
                if c != "`" and j < n and src[j] == "\n":
                    break
                j += 1
            out.append(src[i:j + 1]); i = j + 1
        elif src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i)); i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", src[i:j])); i = j
        else:
            out.append(c); i += 1
    return "".join(out)


_Q = r"""(['"])([^'"\n]+)\1"""
JS_PATTERNS = [
    re.compile(r"""\b(?:import|export)\b[^'";`]*?\bfrom\s*""" + _Q),   # import x from 'a' / export * from 'a'
    re.compile(r"""\bimport\s*""" + _Q),                              # import 'a'
    re.compile(r"""\brequire\s*\(\s*""" + _Q + r"""\s*\)"""),         # require('a')
    re.compile(r"""\bimport\s*\(\s*""" + _Q + r"""\s*\)"""),          # import('a')
]


def js_imports(source: str):
    text = strip_js_comments(source)
    seen, out = set(), []
    for rx in JS_PATTERNS:
        for m in rx.finditer(text):
            spec = m.group(2)
            if spec not in seen:
                seen.add(spec); out.append(spec)
    return out


def load_tsconfig_paths(root: str):
    """-> list of (prefix, [target prefixes]) from tsconfig.json compilerOptions.paths (+ baseUrl); [] if absent/unparseable."""
    p = os.path.join(root, "tsconfig.json")
    try:
        text = strip_js_comments(open(p, encoding="utf-8").read())
        data = json.loads(re.sub(r",(\s*[}\]])", r"\1", text))
        co = data.get("compilerOptions", {})
        base = posixpath.normpath(co.get("baseUrl", ".") or ".")
        out = []
        for pat, targets in (co.get("paths") or {}).items():
            if pat.endswith("*"):
                out.append((pat[:-1], [posixpath.normpath(posixpath.join(base, t[:-1] if t.endswith("*") else t)) for t in targets]))
        return out
    except (OSError, ValueError, AttributeError):
        return []


def _js_candidates(base: str):
    yield base
    m = re.match(r"^(.*)\.(js|jsx|mjs|cjs)$", base)
    if m:  # ESM-style './x.js' that is really x.ts
        for e in {"js": (".ts", ".tsx"), "jsx": (".tsx",), "mjs": (".mts",), "cjs": (".cts",)}[m.group(2)]:
            yield m.group(1) + e
    for e in JS_EXT:
        yield base + e
    for e in JS_EXT:
        yield posixpath.join(base, "index" + e)


def resolve_js(src: str, spec: str, files: dict, aliases):
    """-> ('file', rel) | ('external', name) | ('unresolved', spec)."""
    bases = []
    if spec.startswith("."):
        bases.append(posixpath.normpath(posixpath.join(posixpath.dirname(src), spec)))
    else:
        for prefix, targets in aliases:
            if spec.startswith(prefix):
                bases += [posixpath.normpath(posixpath.join(t, spec[len(prefix):])) if spec[len(prefix):] else t for t in targets]
    for b in bases:
        for c in _js_candidates(b):
            if c in files:
                return "file", c
    if spec.startswith("."):
        return "unresolved", spec
    parts = spec.split("/")
    name = "/".join(parts[:2]) if spec.startswith("@") else parts[0]
    return "external", name


# ---------------------------------------------------------------- driver

def scan(root: str, exclude=()) -> Scan:
    s = Scan()
    s.files = collect(root, exclude)
    aliases = load_tsconfig_paths(root)
    for rel, lang in s.files.items():
        full = os.path.join(root, rel)
        try:
            if os.path.getsize(full) > MAX_BYTES:
                s.skipped.append([rel, "larger than 2 MB"]); continue
            text = open(full, encoding="utf-8", errors="replace").read()
            if lang == "python":
                for level, module, names in py_imports(text):
                    hits = resolve_py(rel, level, module, names, s.files)
                    for h in hits:
                        if h != rel:
                            s.edges[(rel, h)] = s.edges.get((rel, h), 0) + 1
                    if not hits and not level:
                        ext = external_py(module)
                        if ext:
                            s.externals.setdefault(rel, set()).add(ext)
            else:
                for spec in js_imports(text):
                    kind, val = resolve_js(rel, spec, s.files, aliases)
                    if kind == "file" and val != rel:
                        s.edges[(rel, val)] = s.edges.get((rel, val), 0) + 1
                    elif kind == "external":
                        s.externals.setdefault(rel, set()).add(val)
        except SyntaxError as e:
            s.skipped.append([rel, f"python syntax error line {e.lineno}"])
        except (OSError, ValueError) as e:
            s.skipped.append([rel, f"{type(e).__name__}: {e}"])
    return s
