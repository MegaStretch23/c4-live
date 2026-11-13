#!/bin/sh
# Re-creates every other file in examples/ from two pinned public repos (needs network + git). Run from the repo root.
set -e
W=$(mktemp -d)
git clone -q https://github.com/psf/requests "$W/requests"
git -C "$W/requests" checkout -q 6e83187b8feb273ed4c6cdab5efd8d54901dfab3      # tag v2.34.2
git clone -q https://github.com/sindresorhus/ky "$W/ky"
git -C "$W/ky" checkout -q 3541888878c4d303a8bc2ad61815f4e048f55a5d
git -C "$W/requests" fetch -q origin tag v2.31.0 --no-tags
python3 -m c4_live scan "$W/requests" --name requests --level container -o examples/requests-container.mmd 2> examples/requests-scan.stderr.txt
python3 -m c4_live scan "$W/requests" --name requests --level component --container requests -o examples/requests-component.mmd 2>/dev/null
python3 -m c4_live diff v2.31.0 v2.34.2 --repo "$W/requests" --name requests --level container -o examples/requests-diff-container.txt 2> examples/requests-diff.stderr.txt
python3 -m c4_live diff v2.31.0 v2.34.2 --repo "$W/requests" --name requests --level component -o examples/requests-diff-component.txt 2>/dev/null
python3 -m c4_live scan "$W/ky" --name ky --level container -o examples/ky-container.mmd 2> examples/ky-scan.stderr.txt
rm -rf "$W"
