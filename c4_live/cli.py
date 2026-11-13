from __future__ import annotations

import argparse
import sys

from . import __version__
from .core import diff_edges, scan_dir, scan_ref
from .render import as_json, diff_text, diff_view, graph_view, mermaid, plantuml

FORMATS = {"mermaid": mermaid, "plantuml": plantuml, "json": as_json}


def _summary(g, label: str) -> str:
    langs = {}
    for f, l in g.lang.items():
        langs[l] = langs.get(l, 0) + 1
    s = f"{label}: {len(g.lang)} files ({', '.join(f'{n} {l}' for l, n in sorted(langs.items())) or 'none'}), " \
        f"{sum(g.edges.values())} internal and {sum(g.ext_edges.values())} external import statements"
    if g.skipped:
        s += f", {len(g.skipped)} file(s) skipped as unparsable (first: {g.skipped[0][0]})"
    return s


def _emit(text: str, out: str | None):
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="c4-live", description="C4 architecture diagrams and diffs from Python / TypeScript imports.")
    ap.add_argument("--version", action="version", version=f"c4-live {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--include-tests", action="store_true", help="count test files (default: skipped)")
    common.add_argument("--strip", help="path prefix to drop before clustering (default: auto)")
    common.add_argument("--name", help="system name in the diagram (default: the directory name)")
    common.add_argument("-o", "--output", help="write to a file instead of stdout")
    s = sub.add_parser("scan", parents=[common], help="diagram the current tree")
    s.add_argument("path", nargs="?", default=".")
    s.add_argument("--level", choices=["context", "container", "component", "module"], default="container")
    s.add_argument("--container", help="component view: only this container and its neighbours")
    s.add_argument("--format", choices=list(FORMATS), default="mermaid")
    d = sub.add_parser("diff", parents=[common], help="edges added / removed between two git refs")
    d.add_argument("ref_a")
    d.add_argument("ref_b")
    d.add_argument("--repo", default=".")
    d.add_argument("--level", choices=["container", "component", "module"], default="component")
    d.add_argument("--format", choices=["text", *FORMATS], default="text")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "scan":
            g = scan_dir(a.path, a.include_tests, a.strip)
            g.name = a.name or g.name
            print(_summary(g, a.path), file=sys.stderr)
            _emit(FORMATS[a.format](graph_view(g, a.level, a.container)), a.output)
        else:
            ga = scan_ref(a.repo, a.ref_a, a.include_tests, a.strip)
            gb = scan_ref(a.repo, a.ref_b, a.include_tests, a.strip)
            ga.name = gb.name = a.name or gb.name
            print(_summary(ga, a.ref_a), file=sys.stderr)
            print(_summary(gb, a.ref_b), file=sys.stderr)
            if a.format == "text":
                _emit(diff_text(ga, gb, a.level, a.ref_a, a.ref_b), a.output)
            else:
                _emit(FORMATS[a.format](diff_view(ga, gb, a.level, a.ref_a, a.ref_b)), a.output)
    except ValueError as e:
        print(f"c4-live: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
