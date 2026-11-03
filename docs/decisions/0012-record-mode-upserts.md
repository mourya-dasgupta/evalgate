# 0012. Record mode upserts; it does not prune stale entries

- Status: Accepted
- Date: 2026-11-03

## Context

One suite often needs recordings for several variants (the demo records both prompt
versions into one cassette). Pruning "unused" entries on every record would delete the
other variant's recordings.

## Decision

`--mode record` calls the provider for every case and upserts the responses into the
cassette (keyed by request hash). Entries are written sorted by key for minimal diffs.
Nothing is pruned automatically; to start clean, delete the cassette file before recording
(as `examples/support-triage/record.sh` does).

## Consequences

- Recording variants one at a time is safe.
- Stale entries can accumulate; they are harmless for correctness (they are never matched)
  but add weight. A `cassette prune` command is on the roadmap.
