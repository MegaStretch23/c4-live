# c4diff

Architecture diagram **and diff** from your imports. Point it at a Python and/or TypeScript/JavaScript repo and it prints a [Mermaid C4](https://mermaid.js.org/syntax/c4.html) diagram (or JSON) of how the top-level folders and modules depend on each other. Point it at two git refs or two folders and it lists the dependency edges that were **added, removed or changed**, optionally as a diagram with the changes colored.

- Python 3.9+, **standard library only**. No `pip install` of anything to run it.
- Python imports are read with `ast`. TypeScript/JS imports are read with a regex pass over `import ... from`, `export ... from`, `import 'x'`, `require('x')` and `import('x')` (comments are blanked first; `tsconfig.json` `paths` aliases are followed).
- Files are grouped into C4 **containers** (top-level folder; a leading `src/`, `lib/`, `packages/`... is skipped) and **components** (the next folder or module). An edge means "at least one file in A imports a file in B"; its weight is the number of distinct file pairs.
- It is a static import graph. It does not see runtime calls, dynamic strings, reflection, or anything outside the files it scans. It is not a live viewer: re-run it, or paste the output into [mermaid.live](https://mermaid.live).

## Quickstart

```bash
git clone https://github.com/MegaStretch23/c4-diff.git
cd c4-diff

# diagram of any folder (here: this tool's own source)
python -m c4diff graph c4diff

# the same as JSON
python -m c4diff graph c4diff --format json

# what changed between two git refs of a repo
python -m c4diff diff v1.0 v1.1 --repo /path/to/repo
# ...as a Mermaid diagram with only the changed nodes and edges colored
python -m c4diff diff v1.0 v1.1 --repo /path/to/repo --format mermaid --only-changes
```

Options: `--depth 1` (containers only) or `2` (default, adds components), `--path SUBDIR` (scan only that folder on each side, e.g. `src`), `--exclude 'tests/*'` (repeatable), `--externals` (draw third-party packages, depth 1), `-o FILE`, `--exit-code` on `diff` (exit 1 if the sides differ, for CI). A folder argument is used as is; anything else is a git ref in `--repo` (default `.`). Files that cannot be parsed are listed on stderr, never silently dropped; errors exit 2.

Tests: `pip install pytest && python -m pytest` (12 tests, build their own Python and TypeScript fixture repos in a temp dir).

## Real sample output

Both runs below were made with this exact code on public repos.

**Diff: `psf/requests` v2.31.0 -> v2.32.0** (`docs/` and `ext/` excluded; commits `147c8511d` and `d6ebc4a2f`):

```text
c4diff: v2.31.0 -> v2.32.0
nodes added (1)
  tests/test_adapters
nodes removed (0)
edges added (3)
  + requests/packages -> requests/compat  (1 file)
  + tests/test_adapters -> requests/adapters  (1 file)
  + tests/test_requests -> tests/testserver  (1 file)
edges removed (0)
edges changed (0)
```

The `packages -> compat` edge was checked by hand: v2.32.0's `packages.py` has `from .compat import chardet`, where v2.31.0 imported `chardet` directly. (v2.32.0 also moved the package into `src/`; the `src/` prefix is skipped, so the two sides line up.) The Mermaid form with `--only-changes` is in [`examples/requests-2.31-to-2.32-changes.mmd`](examples/requests-2.31-to-2.32-changes.mmd); at container depth the same pair of releases shows `tests -> requests` going from 24 to 25 files. The other two edges come from a test file that is new in v2.32.0 and a test importing the test server.

**Graph: `sindresorhus/ky` @ `3541888`, `--path source --depth 1`** (TypeScript, 31 files, 93 file-level import links):

```text
C4Container
  title ky
  Container(n_root, "(root)", "TypeScript/JS", "1 file")
  Container(n_core, "core", "TypeScript/JS", "3 files")
  Container(n_errors, "errors", "TypeScript/JS", "8 files")
  Container(n_types, "types", "TypeScript/JS", "9 files")
  Container(n_utils, "utils", "TypeScript/JS", "10 files")
  Rel(n_root, n_core, "imports (2 files)")
  Rel(n_root, n_errors, "imports (7 files)")
  ...
```

Full files: [`ky-containers.mmd`](examples/ky-containers.mmd), [`ky-components.mmd`](examples/ky-components.mmd), [`ky-graph.json`](examples/ky-graph.json), [`requests-containers.mmd`](examples/requests-containers.mmd).

About the diagrams: Mermaid marks its C4 diagrams experimental. In this build every example above was accepted by Mermaid's own parser (`mermaid.parse`, mermaid from npm); I did not render them to images, so check the layout in mermaid.live for large graphs.

## Limits (read these)

- TypeScript/JS parsing is regex-based: string-literal specifiers only (no template-literal `import(\`./${x}\`)`), and a regex literal containing quotes can confuse the comment/string scanner. Only `tsconfig.json` `paths` with a trailing `*` are followed (no `extends`, no bundler aliases).
- Python: absolute imports are resolved against the importing file's folder and its parents (and `src/`). `sys.path` tricks and imports inside strings do not.
- A renamed folder shows up as one removed and one added node, not a rename.
- Third-party names are the first import segment, so a Python package whose import name differs from its PyPI name is listed by import name.

## Related

[`MegaStretch23/c4-live`](https://github.com/MegaStretch23/c4-live) is a separate implementation of the same idea (it also writes PlantUML). The two were built independently on the same day; use whichever fits. c4diff's differences: JSON graph output, `tsconfig.json` `paths` aliases, a `--only-changes` diff diagram, changed-weight edges in the diff and `--exit-code` for CI.

I also run hosted data tools on Apify, for example the pay-per-event [SEC Form 4 insider cluster scanner](https://apify.com/johnveds15/sec-form4-insider-clusters). They do something different from this tool; there is no paid version of c4diff.

## License

MIT.
