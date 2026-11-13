# c4-live

Scan a Python or TypeScript repo into a [C4 model](https://c4model.com) (system context, containers, components), print it as
**Mermaid C4**, **Structurizr DSL** or JSON, and **diff** the model between two git refs: which components and relations were added,
removed or changed. Standard library only, Python 3.10+, MIT licence.

- Python: `ast` import analysis. Top-level package = container, module = component.
- TypeScript / JavaScript: a regex import parser (no tree-sitter). Nearest `package.json` directory = container (npm workspaces
  included), file = component. Reads static `import ... from`, `export ... from`, `import()` and `require()` with string literals.
- `diff` exports each ref with `git archive` into a temp dir, scans both and compares. Your working tree and index are not touched.

## Quickstart

```
git clone https://github.com/MegaStretch23/c4-live
cd c4-live
python3 -m c4_live scan . --format mermaid          # or: pip install .  ->  c4-live scan ...
python3 -m c4_live scan . --format dsl
python3 -m c4_live diff . --base HEAD~1 --head HEAD  # any repo with 2+ commits
python3 -m pytest                                    # pip install pytest first
```

`scan <path> [--format mermaid|dsl|json] [--level context|container|component|all] [--include-tests] [-o FILE]`
`diff <path> [--base REF] [--head REF] [--format markdown|json] [--fail-on-change] [--include-tests] [-o FILE]`
(`--head WORKTREE` compares against the files on disk, uncommitted changes included. Tests and `node_modules`, `venv`, `dist` etc. are skipped by default.)

## Sample output (saved from real runs; regenerate with `bash examples/run_demo.sh`)

`examples/self-scan.mmd`, `.dsl` and `.json` are c4-live scanning its own repository. The TypeScript workspace fixture
(`tests/fixtures/ts_repo`, container level, `examples/ts-fixture-containers.mmd`):

```
%% Containers
C4Container
  title Containers: ts_repo
  System_Boundary(sys_ts_repo_b, "ts_repo") {
    Container(c__fx_core, "@fx/core", "npm workspace package", "3 modules, path packages/core")
    Container(c__fx_web, "@fx/web", "npm workspace package", "4 modules, path packages/web")
  }
  System_Ext(ext_lodash, "lodash", "third-party package")
  System_Ext(ext_react, "react", "third-party package")
  Rel(c__fx_web, c__fx_core, "imports")
  Rel(c__fx_core, ext_lodash, "imports")
  Rel(c__fx_web, ext_react, "imports")
```

The `diff` demo runs on a throwaway git repo built from the Python fixture (`tests/fixtures/py_repo`): commit 1 is the fixture, commit 2
adds `shop/tax.py` and removes the `billing -> shop` import. Saved as `examples/diff-demo.md` (and `.json`):

```
# C4 diff: shop-demo

`HEAD~1` -> `HEAD`

## Containers
### Relations removed (2)
- `billing` -> `shop`
- `shop` -> `billing`

## Components
### Added (1)
- `shop/tax`

### Changed (1)
- `shop/cart`: dropped external imports: requests

### Relations added (2)
- `shop/cart` -> `shop/tax`
- `shop/tax` -> `shop/prices`

### Relations removed (2)
- `billing/invoice` -> `shop/prices`
- `shop/cart` -> `billing/invoice`
```

In CI, `diff --fail-on-change` exits 1 when the architecture changed (the demo above exited with 1), 0 when it did not, and 2 on an error such as an unknown ref.

## Limits

- Relations are import edges between modules in the scanned tree. Calls, inheritance, runtime wiring, dynamic imports built from variables and
  infrastructure (queues, databases, HTTP between services) are not detected.
- Python containers are top-level packages (`src/` layout is handled); loose top-level `.py` files go in a `root-modules` container.
- The TypeScript parser is regex based: it can miss unusual import syntax and does not read `tsconfig.json` path aliases.
- Mermaid and Structurizr output is generated from the documented syntax of each format; it has been unit tested here but not validated
  against the Mermaid renderer or the Structurizr tooling. Large repos produce large component diagrams: use `--level container`.

## Hosted and paid options

c4-live is free and complete as it stands. If you want related tools from the same author:

- [blame-ai: AI-assist ledger for your git history (Python, local, no dependencies)](https://vedovino.gumroad.com/l/smhyy?utm_source=github) - Gumroad source pack, $19
- [Patch-Conflict Kit: GitHub Action + CLI that flag duplicate and conflicting PRs for one issue](https://vedovino.gumroad.com/l/hhfiwl?utm_source=github) - Gumroad source pack, $15
- [Trace-conformance checker: replay JSONL logs against a state machine](https://vedovino.gumroad.com/l/eeedk?utm_source=github) - Gumroad source pack, $19
- Apify actors (pay per event, run in the cloud): [AI API Key Leak Scanner: GitHub Repos + URLs](https://apify.com/johnveds15/ai-api-key-leak-scanner), [CVE Vulnerability Scraper: NIST NVD, No API Key](https://apify.com/johnveds15/openvuln-cve-scanner)

None of these are needed to use c4-live.

## Licence

MIT, see `LICENSE`.
