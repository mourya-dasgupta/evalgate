#!/usr/bin/env bash
# Re-record the demo cassettes from the SIMULATED model (sim_model.py) for both
# prompt versions, then refresh the committed v1 baseline.
# For a real model, see README.md ("Re-recording with a real model").
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
EG="${EVALGATE:-evalgate}"

rm -f cassettes/triage.jsonl   # start clean so stale recordings do not accumulate
for version in v1 v2_regressed; do
  echo "Recording prompts/${version}.txt"
  TRIAGE_PROMPT="$version" $EG --mode record run --suite triage > /dev/null
done
$EG run --suite triage > /dev/null
$EG baseline update
