"""Diff two C4 models, or two git refs of one repo."""
from __future__ import annotations

import io
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

from .model import Model
from .scan import scan

WORKTREE = "WORKTREE"   # pseudo-ref: the files on disk, uncommitted changes included


class GitError(RuntimeError):
    pass


def _git(repo: Path, *args: str, binary: bool = False):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, env=env)
    if r.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {r.stderr.decode('utf-8', 'replace').strip()}")
    return r.stdout if binary else r.stdout.decode("utf-8", "replace").strip()


def scan_ref(path: str | Path, ref: str, include_tests: bool = False) -> Model:
    """Scan `path` as it was at git `ref` (a copy exported with `git archive`; the repo and working tree are untouched)."""
    path = Path(path).resolve()
    if ref == WORKTREE:
        return scan(path, name=path.name, include_tests=include_tests)
    top = Path(_git(path, "rev-parse", "--show-toplevel"))
    prefix = path.relative_to(top).as_posix()
    _git(top, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
    args = ["archive", "--format=tar", ref] + ([prefix] if prefix != "." else [])
    data = _git(top, *args, binary=True)
    with tempfile.TemporaryDirectory(prefix="c4live-") as td:
        with tarfile.open(fileobj=io.BytesIO(data)) as tf:
            tf.extractall(td, filter="data") if hasattr(tarfile, "data_filter") else tf.extractall(td)
        root = Path(td) / prefix if prefix != "." else Path(td)
        if not root.is_dir():
            return Model(system=path.name)
        return scan(root, name=path.name, include_tests=include_tests)


def diff_models(a: Model, b: Model) -> dict:
    ac = {c.id: c for c in a.components}
    bc = {c.id: c for c in b.components}
    changed = []
    for cid in sorted(ac.keys() & bc.keys()):
        x, y = ac[cid], bc[cid]
        why = []
        if x.path != y.path:
            why.append(f"path {x.path} -> {y.path}")
        if x.technology != y.technology:
            why.append(f"technology {x.technology} -> {y.technology}")
        added = sorted(set(y.externals) - set(x.externals))
        gone = sorted(set(x.externals) - set(y.externals))
        if added:
            why.append("new external imports: " + ", ".join(added))
        if gone:
            why.append("dropped external imports: " + ", ".join(gone))
        if why:
            changed.append({"id": cid, "changes": why})
    acont = {c.id: c for c in a.containers}
    bcont = {c.id: c for c in b.containers}
    cont_changed = []
    for cid in sorted(acont.keys() & bcont.keys()):
        x, y = acont[cid], bcont[cid]
        why = []
        if x.path != y.path:
            why.append(f"path {x.path} -> {y.path}")
        if x.technology != y.technology:
            why.append(f"technology {x.technology} -> {y.technology}")
        if why:
            cont_changed.append({"id": cid, "changes": why})
    ar = {(r.src, r.dst) for r in a.relations}
    br = {(r.src, r.dst) for r in b.relations}
    acr, bcr = set(a.container_relations()), set(b.container_relations())
    d = {
        "system": b.system,
        "containers": {"added": sorted(bcont.keys() - acont.keys()), "removed": sorted(acont.keys() - bcont.keys()),
                       "changed": cont_changed},
        "components": {"added": sorted(bc.keys() - ac.keys()), "removed": sorted(ac.keys() - bc.keys()), "changed": changed},
        "relations": {"added": [list(p) for p in sorted(br - ar)], "removed": [list(p) for p in sorted(ar - br)]},
        "container_relations": {"added": [list(p) for p in sorted(bcr - acr)], "removed": [list(p) for p in sorted(acr - bcr)]},
    }
    d["changed"] = any(d[k][s] for k in ("containers", "components") for s in ("added", "removed", "changed")) or \
        any(d[k][s] for k in ("relations", "container_relations") for s in ("added", "removed"))
    return d


def to_markdown(d: dict, base: str = "base", head: str = "head") -> str:
    L = [f"# C4 diff: {d['system']}", "", f"`{base}` -> `{head}`", ""]
    if not d["changed"]:
        return "\n".join(L + ["No architectural change: same containers, components and relations.", ""])

    def sec(title, items, fmt=lambda x: f"`{x}`"):
        if items:
            L.append(f"### {title} ({len(items)})")
            L.extend(f"- {fmt(i)}" for i in items)
            L.append("")

    arrow = lambda p: f"`{p[0]}` -> `{p[1]}`"
    L.append("## Containers")
    sec("Added", d["containers"]["added"]); sec("Removed", d["containers"]["removed"])
    sec("Changed", d["containers"]["changed"], lambda x: f"`{x['id']}`: " + "; ".join(x["changes"]))
    sec("Relations added", d["container_relations"]["added"], arrow)
    sec("Relations removed", d["container_relations"]["removed"], arrow)
    L.append("## Components")
    sec("Added", d["components"]["added"]); sec("Removed", d["components"]["removed"])
    sec("Changed", d["components"]["changed"], lambda x: f"`{x['id']}`: " + "; ".join(x["changes"]))
    sec("Relations added", d["relations"]["added"], arrow)
    sec("Relations removed", d["relations"]["removed"], arrow)
    return "\n".join(L).rstrip() + "\n"
