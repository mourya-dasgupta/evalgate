#!/usr/bin/env bash
# The EvalGate demo story, end to end, offline:
#   v1 prompt -> baseline -> "simplified" v2 prompt -> gate FAILS -> back to v1 -> gate PASSES
# Runs in a temporary copy so the repository is not modified (except docs/assets/).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
ASSETS="$ROOT/docs/assets"
EG="${EVALGATE:-evalgate}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

mkdir -p "$ASSETS"
cp -R "$HERE/evalgate.yaml" "$HERE/sim_model.py" "$HERE/prompts" "$HERE/golden" \
  "$HERE/schemas" "$HERE/cassettes" "$WORK/"
cd "$WORK"
start=$(date +%s)

step "1/4  Run the 66-case golden set against prompts/v1.txt (replayed from cassettes)"
$EG run

step "2/4  Promote that run to the baseline"
$EG baseline update

step "3/4  A teammate 'simplifies' the prompt (prompts/v2_regressed.txt). The gate should FAIL"
set +e
TRIAGE_PROMPT=v2_regressed $EG gate \
  --report-md "$ASSETS/demo-gate-fail.md" --report-html "$ASSETS/demo-gate-fail.html"
code=$?
set -e
if [ "$code" -ne 1 ]; then
  echo "Expected the gate to fail with exit code 1, got $code" >&2
  exit 1
fi
echo "Gate exited with code $code (FAIL), as expected."

step "4/4  Revert to v1. The gate should PASS"
$EG gate --report-md "$ASSETS/demo-gate-pass.md" --report-html "$ASSETS/demo-gate-pass.html"

step "Done in $(( $(date +%s) - start ))s. Reports saved to docs/assets/ (demo-gate-fail.md/.html, demo-gate-pass.md/.html)"
