"""Mermaid C4 output (graph and diff). Mermaid's C4 support is marked experimental upstream."""
from __future__ import annotations

import re

COLORS = {"added": "#2e7d32", "removed": "#b71c1c", "changed": "#e65100"}


class Ids:
    """Stable Mermaid-safe identifiers: letters/digits/underscore only, unique."""
    def __init__(self):
        self.m, self.used = {}, set()

    def __call__(self, kind: str, key: str) -> str:
        if (kind, key) not in self.m:
            base = f"{kind}_" + (re.sub(r"\W", "_", key).strip("_") or "x")
            cand, i = base, 2
            while cand in self.used:
                cand, i = f"{base}_{i}", i + 1
            self.used.add(cand); self.m[(kind, key)] = cand
        return self.m[(kind, key)]


def q(s) -> str:
    return str(s).replace('"', "'").replace("\n", " ")


def _tech(langs) -> str:
    return " + ".join("Python" if l == "python" else "TypeScript/JS" for l in langs)


def _files(n) -> str:
    return f"{n} file" + ("" if n == 1 else "s")


def mermaid(g: dict, title: str = "", externals: bool = False, d: dict | None = None, only_changes: bool = False) -> str:
    """Render a graph; with `d` (a graph.diff result, graph `g` = the union graph from union()) highlight changes."""
    ids = Ids()
    depth = g["depth"]
    kind = "C4Component" if depth >= 2 else "C4Container"
    status = {}
    edge_status = {}
    if d:
        for n in d["nodes_added"]: status[n] = "added"
        for n in d["nodes_removed"]: status[n] = "removed"
        for e in d["edges_added"]: edge_status[(e["from"], e["to"])] = ("added", f"+ imports ({_files(e['weight'])})")
        for e in d["edges_removed"]: edge_status[(e["from"], e["to"])] = ("removed", f"- imports (was {_files(e['weight'])})")
        for e in d["edges_changed"]: edge_status[(e["from"], e["to"])] = ("changed", f"~ imports ({e['before']} -> {e['after']} files)")
    edges = [e for e in g["edges"] if not only_changes or (e["from"], e["to"]) in edge_status]
    keep = None
    if only_changes:
        keep = {x for e in edges for x in (e["from"], e["to"])} | set(status)
    lines = [kind, f"  title {q(title or g.get('name') or 'architecture')}"]
    conts = {c["id"]: c for c in g["containers"]}
    if depth >= 2:
        by = {}
        for k in g["components"]:
            if keep is None or k["id"] in keep:
                by.setdefault(k["container"], []).append(k)
        for cid in sorted(by):
            lines.append(f'  Container_Boundary({ids("b", cid)}, "{q(cid)}") {{')
            for k in by[cid]:
                label = k["id"].split("/", 1)[1]
                lines.append(f'    Component({ids("n", k["id"])}, "{q(label)}", "{_tech(k["languages"])}", "{_files(k["files"])}")')
            lines.append("  }")
        node_keys = [k["id"] for ks in by.values() for k in ks]
    else:
        node_keys = []
        for cid, c in sorted(conts.items()):
            if keep is None or cid in keep:
                lines.append(f'  Container({ids("n", cid)}, "{q(cid)}", "{_tech(c["languages"])}", "{_files(c["files"])}")')
                node_keys.append(cid)
    if externals and not only_changes and depth < 2:  # externals are tracked per container, so drawn at container depth only
        for n in sorted({n for v in g.get("externals", {}).values() for n in v}):
            lines.append(f'  System_Ext({ids("x", n)}, "{q(n)}", "external package")')
        for cid, v in sorted(g.get("externals", {}).items()):
            for n in v:
                lines.append(f'  Rel({ids("n", cid)}, {ids("x", n)}, "uses")')
    for e in edges:
        st = edge_status.get((e["from"], e["to"]))
        label = st[1] if st else f"imports ({_files(e['weight'])})"
        lines.append(f'  Rel({ids("n", e["from"])}, {ids("n", e["to"])}, "{q(label)}")')
    for e in edges:
        st = edge_status.get((e["from"], e["to"]))
        if st:
            c = COLORS[st[0]]
            lines.append(f'  UpdateRelStyle({ids("n", e["from"])}, {ids("n", e["to"])}, $textColor="{c}", $lineColor="{c}")')
    for n in node_keys:
        if n in status:
            lines.append(f'  UpdateElementStyle({ids("n", n)}, $bgColor="{COLORS[status[n]]}", $borderColor="{COLORS[status[n]]}")')
    return "\n".join(lines) + "\n"


def union(a: dict, b: dict) -> dict:
    """Graph with every node and edge of both sides (edge weight from B when present, else A)."""
    u = dict(b)
    def merge(key, ident):
        seen = {x[ident]: x for x in a[key]}
        seen.update({x[ident]: x for x in b[key]})
        return [seen[k] for k in sorted(seen)]
    u["containers"] = merge("containers", "id")
    u["components"] = merge("components", "id")
    ed = {(e["from"], e["to"]): e for e in a["edges"]}
    ed.update({(e["from"], e["to"]): e for e in b["edges"]})
    u["edges"] = [ed[k] for k in sorted(ed)]
    return u


def text_diff(d: dict, label_a: str, label_b: str) -> str:
    out = [f"c4diff: {label_a} -> {label_b}"]
    def sect(title, rows):
        out.append(f"{title} ({len(rows)})")
        out.extend("  " + r for r in rows)
    sect("nodes added", d["nodes_added"])
    sect("nodes removed", d["nodes_removed"])
    sect("edges added", [f"+ {e['from']} -> {e['to']}  ({_files(e['weight'])})" for e in d["edges_added"]])
    sect("edges removed", [f"- {e['from']} -> {e['to']}  (was {_files(e['weight'])})" for e in d["edges_removed"]])
    sect("edges changed", [f"~ {e['from']} -> {e['to']}  ({e['before']} -> {e['after']} files)" for e in d["edges_changed"]])
    return "\n".join(out) + "\n"
