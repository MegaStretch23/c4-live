"""Cluster file-level edges into C4 containers / components, and diff two graphs."""
from __future__ import annotations

import posixpath

from .scanner import Scan

LAYOUT_DIRS = {"src", "source", "lib", "libs", "packages", "apps"}


def split_path(rel: str):
    """-> (container, component) for a file path. Leading layout dirs (src/, packages/ ...) are skipped when something remains."""
    parts = rel.split("/")
    if len(parts) > 2 and parts[0] in LAYOUT_DIRS:
        parts = parts[1:]
    if len(parts) == 1:
        return "(root)", "(root)/" + posixpath.splitext(parts[0])[0]
    container = parts[0]
    nxt = parts[1] if len(parts) > 2 else posixpath.splitext(parts[1])[0]
    return container, f"{container}/{nxt}"


def build(sc: Scan, depth: int = 2, name: str = "") -> dict:
    """-> plain-dict graph (the JSON output)."""
    comps, conts, langs = {}, {}, {}
    where = {}
    for rel, lang in sc.files.items():
        c, k = split_path(rel)
        where[rel] = (c, k)
        for table, key in ((conts, c), (comps, k)):
            table[key] = table.get(key, 0) + 1
        langs.setdefault(c, set()).add(lang)
        langs.setdefault(k, set()).add(lang)
    key_i = 1 if depth >= 2 else 0
    pairs = {}
    for (a, b) in sc.edges:
        x, y = where[a][key_i], where[b][key_i]
        if x != y:
            pairs[(x, y)] = pairs.get((x, y), 0) + 1   # distinct file->file links
    ext = {}
    for rel, names in sc.externals.items():
        ext.setdefault(where[rel][0], set()).update(names)
    g = {
        "version": 1, "name": name, "depth": 2 if depth >= 2 else 1,
        "stats": {"files": len(sc.files), "python": sum(1 for v in sc.files.values() if v == "python"),
                  "typescript": sum(1 for v in sc.files.values() if v == "typescript"),
                  "file_edges": len(sc.edges), "skipped": sc.skipped},
        "containers": [{"id": c, "files": n, "languages": sorted(langs[c])} for c, n in sorted(conts.items())],
        "components": [{"id": k, "container": k.split("/")[0], "files": n, "languages": sorted(langs[k])} for k, n in sorted(comps.items())] if depth >= 2 else [],
        "edges": [{"from": a, "to": b, "weight": w} for (a, b), w in sorted(pairs.items())],
        "externals": {c: sorted(v) for c, v in sorted(ext.items())},
    }
    return g


def node_ids(g: dict) -> set:
    return {n["id"] for n in (g["components"] if g["depth"] >= 2 else g["containers"])}


def diff(a: dict, b: dict) -> dict:
    """Compare two graphs built at the same depth."""
    if a["depth"] != b["depth"]:
        raise ValueError("graphs were built at different depths")
    ea = {(e["from"], e["to"]): e["weight"] for e in a["edges"]}
    eb = {(e["from"], e["to"]): e["weight"] for e in b["edges"]}
    na, nb = node_ids(a), node_ids(b)
    return {
        "nodes_added": sorted(nb - na), "nodes_removed": sorted(na - nb),
        "edges_added": [{"from": k[0], "to": k[1], "weight": eb[k]} for k in sorted(eb.keys() - ea.keys())],
        "edges_removed": [{"from": k[0], "to": k[1], "weight": ea[k]} for k in sorted(ea.keys() - eb.keys())],
        "edges_changed": [{"from": k[0], "to": k[1], "before": ea[k], "after": eb[k]} for k in sorted(ea.keys() & eb.keys()) if ea[k] != eb[k]],
    }


def has_changes(d: dict) -> bool:
    return any(d[k] for k in ("nodes_added", "nodes_removed", "edges_added", "edges_removed", "edges_changed"))
