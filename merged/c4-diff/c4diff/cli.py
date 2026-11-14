"""c4diff command line."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

from . import __version__, graph, render, scanner, sources


def _build(arg, a, tmp):
    d, label = sources.materialize(arg, a.repo, tmp)
    sub = os.path.join(d, a.path) if a.path else d
    if not os.path.isdir(sub):
        raise sources.SourceError(f"--path {a.path!r} is not a directory in {label}")
    sc = scanner.scan(sub, a.exclude)
    if not sc.files:
        raise sources.SourceError(f"no Python or TypeScript/JS files found in {label}" + (f"/{a.path}" if a.path else ""))
    return graph.build(sc, a.depth, label), label


def _emit(text: str, out) -> None:
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)


def main(argv=None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=".", help="git repository used when an argument is a ref (default: .)")
    common.add_argument("--path", default="", help="only scan this sub-directory of each side (e.g. src)")
    common.add_argument("--depth", type=int, choices=(1, 2), default=2, help="1 = containers only, 2 = containers + components (default)")
    common.add_argument("--exclude", action="append", default=[], metavar="GLOB", help="skip paths matching this glob (repeatable), e.g. 'tests/*'")
    common.add_argument("-o", "--output", help="write to this file instead of stdout")
    ap = argparse.ArgumentParser(prog="c4diff", description="C4-style architecture diagram and diff from Python and TypeScript/JS imports.")
    ap.add_argument("--version", action="version", version=f"c4diff {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("graph", parents=[common], help="diagram of one directory or git ref")
    g.add_argument("source", help="directory, or a git ref in --repo")
    g.add_argument("--format", choices=("mermaid", "json"), default="mermaid")
    g.add_argument("--externals", action="store_true", help="also draw external packages (container depth only)")
    d = sub.add_parser("diff", parents=[common], help="compare two directories or git refs")
    d.add_argument("a"); d.add_argument("b")
    d.add_argument("--format", choices=("text", "mermaid", "json"), default="text")
    d.add_argument("--only-changes", action="store_true", help="mermaid: draw only the nodes and edges that changed")
    d.add_argument("--exit-code", action="store_true", help="exit 1 when the two sides differ (like git diff --exit-code)")
    a = ap.parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix="c4diff-") as td:
            tmp = tempfile.TemporaryDirectory(dir=td)
            try:
                if a.cmd == "graph":
                    gr, label = _build(a.source, a, tmp)
                    for rel, why in gr["stats"]["skipped"]:
                        print(f"c4diff: skipped {rel}: {why}", file=sys.stderr)
                    _emit(json.dumps(gr, indent=2) + "\n" if a.format == "json" else render.mermaid(gr, label, a.externals), a.output)
                    return 0
                ga, la = _build(a.a, a, tmp)
                gb, lb = _build(a.b, a, tmp)
                for lab, gr in ((la, ga), (lb, gb)):
                    for rel, why in gr["stats"]["skipped"]:
                        print(f"c4diff: skipped {rel} ({lab}): {why}", file=sys.stderr)
                df = graph.diff(ga, gb)
                if a.format == "json":
                    text = json.dumps({"from": la, "to": lb, **df}, indent=2) + "\n"
                elif a.format == "mermaid":
                    text = render.mermaid(render.union(ga, gb), f"{la} -> {lb}", d=df, only_changes=a.only_changes)
                else:
                    text = render.text_diff(df, la, lb)
                _emit(text, a.output)
                return 1 if a.exit_code and graph.has_changes(df) else 0
            finally:
                tmp.cleanup()
    except sources.SourceError as e:
        print(f"c4diff: FAILED: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
