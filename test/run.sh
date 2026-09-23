#!/bin/sh
# Run everything. Used before any release, and after touching an adapter.
set -e
cd "$(dirname "$0")/.."

echo "== wiring (python) =="
python3 test/test_wiring.py

echo
echo "== opencode adapter (node) =="
node test/opencode-adapter.mjs

echo
echo "== mutation check =="
python3 test/mutation_check.py
