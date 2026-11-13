"""c4-live scan|diff <path> [--base REF --head REF] [--format ...]"""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__, render
from .diff import WORKTREE, GitError, diff_models, scan_ref, to_markdown
from .scan import scan


def _emit(text: str, out: str | None) -> None:
    if out:
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    else:
        sys.stdout.write(text)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="c4-live", description="C4 model of a Python / TypeScript repo, as Mermaid or Structurizr DSL, plus a git-ref diff.")
    ap.add_argument("--version", action="version", version=f"c4-live {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="scan a directory into a C4 model")
    s.add_argument("path")
    s.add_argument("--format", choices=["mermaid", "dsl", "json"], default="mermaid")
    s.add_argument("--level", choices=list(render.LEVELS), default="all", help="mermaid only (default all)")
    s.add_argument("--include-tests", action="store_true")
    s.add_argument("-o", "--output")
    d = sub.add_parser("diff", help="compare the C4 model at two git refs")
    d.add_argument("path")
    d.add_argument("--base", default="HEAD~1", help="default HEAD~1")
    d.add_argument("--head", default="HEAD", help=f"default HEAD; {WORKTREE} = files on disk")
    d.add_argument("--format", choices=["markdown", "json"], default="markdown")
    d.add_argument("--include-tests", action="store_true")
    d.add_argument("--fail-on-change", action="store_true", help="exit 1 if the architecture changed (for CI)")
    d.add_argument("-o", "--output")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "scan":
            m = scan(args.path, include_tests=args.include_tests)
            text = m.to_json() if args.format == "json" else render.dsl(m) if args.format == "dsl" else render.mermaid(m, args.level)
            _emit(text, args.output)
            return 0
        a = scan_ref(args.path, args.base, args.include_tests)
        b = scan_ref(args.path, args.head, args.include_tests)
        d = diff_models(a, b)
        _emit(json.dumps(d, indent=2) + "\n" if args.format == "json" else to_markdown(d, args.base, args.head), args.output)
        return 1 if (args.fail_on_change and d["changed"]) else 0
    except (GitError, NotADirectoryError, OSError) as e:
        print(f"c4-live: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
