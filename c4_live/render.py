"""Turn graph levels into a neutral View, then print it as Mermaid C4, PlantUML C4 or JSON."""
from __future__ import annotations

import json
import re

from .core import Graph, diff_edges

KIND = {"context": "C4Context", "container": "C4Container", "component": "C4Component", "module": "C4Component"}
PUML = {"context": "C4_Context", "container": "C4_Container", "component": "C4_Component", "module": "C4_Component"}


class View:
    def __init__(self, title: str, level: str):
        self.title, self.level = title, level
        self.nodes: dict[str, dict] = {}     # key -> {label, tech, descr, group, ext}
        self.edges: list[dict] = []          # {a, b, label, status}

    def node(self, key: str, label: str, tech: str = "", descr: str = "", group: str | None = None, ext: bool = False):
        self.nodes.setdefault(key, {"label": label, "tech": tech, "descr": descr, "group": group, "ext": ext})

    def edge(self, a: str, b: str, label: str, status: str = "same"):
        self.edges.append({"a": a, "b": b, "label": label, "status": status})


def _files(n: int) -> str:
    return f"{n} file" + ("" if n == 1 else "s")


def _ext_node(v: View, name: str):
    v.node("ext:" + name, name, descr="external package", ext=True)


def graph_view(g: Graph, level: str, container: str | None = None) -> View:
    v = View(f"{g.name}: {level} view", level)
    if level == "context":
        v.node("system", g.name, "", f"{_files(len(g.lang))}", None)
        for pkg in sorted({p for (_, p) in g.ext_edges}):
            _ext_node(v, pkg)
            v.edge("system", "ext:" + pkg, f"imports ({sum(n for (s, p), n in g.ext_edges.items() if p == pkg)})")
        return v
    internal, ext = g.aggregate(level)
    groups = g.files_of(level)
    keep = None
    if container:
        keep = {k for k in groups if (g.unit(groups[k][0])[0] == container)}
        if not keep:
            raise ValueError(f"no {level} inside container '{container}' (containers: {', '.join(sorted(g.files_of('container')))})")
    for key, fs in groups.items():
        v.node(key, key.split("/")[-1] if level == "component" else key, g.tech(fs), _files(len(fs)),
               g.unit(fs[0])[0] if level == "component" else None)
    for (a, b), n in sorted(internal.items()):
        if keep is None or a in keep or b in keep:
            v.edge(a, b, f"imports ({n})")
    for (a, p), n in sorted(ext.items()):
        if keep is None or a in keep:
            _ext_node(v, p)
            v.edge(a, "ext:" + p, f"imports ({n})")
    if keep is not None:
        used = {e["a"] for e in v.edges} | {e["b"] for e in v.edges} | keep
        v.nodes = {k: x for k, x in v.nodes.items() if k in used}
    return v


def diff_view(a: Graph, b: Graph, level: str, ref_a: str, ref_b: str) -> View:
    d = diff_edges(a, b, level)
    v = View(f"{b.name}: {level} changes {ref_a} -> {ref_b}", level)
    groups = {**a.files_of(level), **b.files_of(level)}
    graphs = {}
    for g in (a, b):
        for k, fs in g.files_of(level).items():
            graphs[k] = (g, fs)

    def add(key: str):
        if key.startswith("ext:"):
            _ext_node(v, key[4:])
        else:
            g, fs = graphs[key]
            v.node(key, key.split("/")[-1] if level == "component" else key, g.tech(fs), _files(len(fs)), g.unit(fs[0])[0] if level == "component" else None)
    for status, edges, w in (("added", d["added"], d["weights_b"]), ("removed", d["removed"], d["weights_a"])):
        for s, t in edges:
            add(s)
            add(t)
            v.edge(s, t, f"{status} ({w[(s, t)]})", status)
    return v


def _id(key: str, seen: dict[str, str]) -> str:
    if key not in seen:
        base = re.sub(r"\W", "_", key).strip("_") or "n"
        cand, i = base, 2
        while cand in seen.values():
            cand, i = f"{base}_{i}", i + 1
        seen[key] = cand
    return seen[key]


def _q(s: str) -> str:
    return s.replace('"', "'").replace("\n", " ")


def mermaid(v: View) -> str:
    ids: dict[str, str] = {}
    out = [KIND[v.level], f'  title {_q(v.title)}']
    fn = "Component" if v.level in ("component", "module") else ("Container" if v.level == "container" else "System")
    boundary = {"container": 'System_Boundary', "component": "Container_Boundary", "module": "Container_Boundary"}.get(v.level)
    inside = {k: x for k, x in v.nodes.items() if not x["ext"]}
    for k, x in v.nodes.items():
        if x["ext"]:
            out.append(f'  System_Ext({_id(k, ids)}, "{_q(x["label"])}", "{_q(x["descr"])}")')
    if v.level == "component" or v.level == "module":
        for grp in sorted({x["group"] for x in inside.values() if x["group"]}):
            out.append(f'  Container_Boundary({_id("grp:" + grp, ids)}, "{_q(grp)}") {{')
            for k, x in inside.items():
                if x["group"] == grp:
                    out.append(f'    Component({_id(k, ids)}, "{_q(x["label"])}", "{_q(x["tech"])}", "{_q(x["descr"])}")')
            out.append("  }")
        for k, x in inside.items():
            if not x["group"]:
                out.append(f'  Component({_id(k, ids)}, "{_q(x["label"])}", "{_q(x["tech"])}", "{_q(x["descr"])}")')
    elif v.level == "container":
        out.append(f'  System_Boundary(sys, "{_q(v.title.split(":")[0])}") {{')
        for k, x in inside.items():
            out.append(f'    Container({_id(k, ids)}, "{_q(x["label"])}", "{_q(x["tech"])}", "{_q(x["descr"])}")')
        out.append("  }")
    else:
        for k, x in inside.items():
            out.append(f'  System({_id(k, ids)}, "{_q(x["label"])}", "{_q(x["descr"])}")')
    for e in v.edges:
        out.append(f'  Rel({_id(e["a"], ids)}, {_id(e["b"], ids)}, "{_q(e["label"])}")')
    for e in v.edges:
        if e["status"] != "same":
            c = "green" if e["status"] == "added" else "red"
            out.append(f'  UpdateRelStyle({_id(e["a"], ids)}, {_id(e["b"], ids)}, $textColor="{c}", $lineColor="{c}")')
    return "\n".join(out) + "\n"


def plantuml(v: View) -> str:
    ids: dict[str, str] = {}
    out = ["@startuml", f"!include https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/{PUML[v.level]}.puml", f"title {_q(v.title)}"]
    if any(e["status"] != "same" for e in v.edges):
        out += ['AddRelTag("added", $textColor="green", $lineColor="green")', 'AddRelTag("removed", $textColor="red", $lineColor="red")']
    inside = {k: x for k, x in v.nodes.items() if not x["ext"]}
    for k, x in v.nodes.items():
        if x["ext"]:
            out.append(f'System_Ext({_id(k, ids)}, "{_q(x["label"])}", "{_q(x["descr"])}")')
    if v.level in ("component", "module"):
        for grp in sorted({x["group"] for x in inside.values() if x["group"]}):
            out.append(f'Container_Boundary({_id("grp:" + grp, ids)}, "{_q(grp)}") {{')
            for k, x in inside.items():
                if x["group"] == grp:
                    out.append(f'  Component({_id(k, ids)}, "{_q(x["label"])}", "{_q(x["tech"])}", "{_q(x["descr"])}")')
            out.append("}")
        for k, x in inside.items():
            if not x["group"]:
                out.append(f'Component({_id(k, ids)}, "{_q(x["label"])}", "{_q(x["tech"])}", "{_q(x["descr"])}")')
    elif v.level == "container":
        out.append(f'System_Boundary(sys, "{_q(v.title.split(":")[0])}") {{')
        for k, x in inside.items():
            out.append(f'  Container({_id(k, ids)}, "{_q(x["label"])}", "{_q(x["tech"])}", "{_q(x["descr"])}")')
        out.append("}")
    else:
        for k, x in inside.items():
            out.append(f'System({_id(k, ids)}, "{_q(x["label"])}", "{_q(x["descr"])}")')
    for e in v.edges:
        tag = f', $tags="{e["status"]}"' if e["status"] != "same" else ""
        out.append(f'Rel({_id(e["a"], ids)}, {_id(e["b"], ids)}, "{_q(e["label"])}"{tag})')
    out.append("@enduml")
    return "\n".join(out) + "\n"


def as_json(v: View) -> str:
    return json.dumps({"title": v.title, "level": v.level, "nodes": v.nodes, "edges": v.edges}, indent=2, sort_keys=True) + "\n"


def diff_text(a: Graph, b: Graph, level: str, ref_a: str, ref_b: str) -> str:
    d = diff_edges(a, b, level)
    out = [f"c4-live diff {ref_a} -> {ref_b} (level: {level})"]
    for n in d["added_nodes"]:
        out.append(f"+ node {n}")
    for n in d["removed_nodes"]:
        out.append(f"- node {n}")
    for s, t in d["added"]:
        out.append(f"+ {s} -> {t}  ({d['weights_b'][(s, t)]} import statements)")
    for s, t in d["removed"]:
        out.append(f"- {s} -> {t}  ({d['weights_a'][(s, t)]} import statements)")
    if len(out) == 1:
        out.append("no edge changes")
    out.append(f"{len(d['added'])} edge(s) added, {len(d['removed'])} removed")
    return "\n".join(out) + "\n"
