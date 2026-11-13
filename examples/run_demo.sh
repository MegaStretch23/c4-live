#!/usr/bin/env bash
# Regenerates every file in examples/ from a real run. Run from the repo root:  bash examples/run_demo.sh
set -euo pipefail
cd "$(dirname "$0")/.."
C4="python3 -m c4_live"
OUT=examples

# 1) scan this repository (c4-live scanning itself)
$C4 scan . --format mermaid > $OUT/self-scan.mmd
$C4 scan . --format dsl     > $OUT/self-scan.dsl
$C4 scan . --format json    > $OUT/self-scan.json

# 2) scan the TypeScript workspace fixture
$C4 scan tests/fixtures/ts_repo --format mermaid --level container > $OUT/ts-fixture-containers.mmd

# 3) diff demo: copy the Python fixture into a throwaway git repo, commit, change it, commit, diff
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp -r tests/fixtures/py_repo "$TMP/shop-demo"
cd "$TMP/shop-demo"
export GIT_AUTHOR_NAME=demo GIT_AUTHOR_EMAIL=demo@example.com GIT_COMMITTER_NAME=demo GIT_COMMITTER_EMAIL=demo@example.com
git init -q -b main && git add -A && git commit -q -m "base"
printf 'import numpy\nfrom . import prices\n' > shop/tax.py
printf 'from . import tax\nfrom . import prices\n' > shop/cart.py
printf 'def make_invoice(items):\n    return {}\n' > billing/invoice.py
git add -A && git commit -q -m "add tax, drop billing->shop import"
cd - >/dev/null
( cd "$TMP/shop-demo" && PYTHONPATH="$OLDPWD" python3 -m c4_live diff . --base HEAD~1 --head HEAD --format markdown ) > $OUT/diff-demo.md
( cd "$TMP/shop-demo" && PYTHONPATH="$OLDPWD" python3 -m c4_live diff . --base HEAD~1 --head HEAD --format json )     > $OUT/diff-demo.json
set +e
( cd "$TMP/shop-demo" && PYTHONPATH="$OLDPWD" python3 -m c4_live diff . --base HEAD~1 --head HEAD --fail-on-change >/dev/null ); echo "exit code with --fail-on-change: $?" > $OUT/diff-demo-exit.txt
