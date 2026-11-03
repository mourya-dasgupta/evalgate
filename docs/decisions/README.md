# Architecture decision records

Short records of the decisions that shaped EvalGate, the alternatives considered, and
the trade-offs accepted. Format: context, decision, consequences.

| # | Decision |
|---|---|
| [0001](0001-cassettes-for-determinism.md) | Record model responses once as cassettes; replay them in CI |
| [0002](0002-cassette-key-hashes-rendered-request.md) | The cassette key hashes model + rendered messages + params |
| [0003](0003-no-database-files-in-git.md) | No database: runs, baselines and cassettes are files in git |
| [0004](0004-exit-codes-are-a-contract.md) | Distinct exit codes for pass, gate failure, config error, provider error |
| [0005](0005-pluggable-scorer-registry.md) | Scorers are a registry with per-scorer option validation |
| [0006](0006-llm-judge-through-provider-and-cassette.md) | The LLM judge goes through the same provider + cassette layer |
| [0007](0007-case-pass-semantics.md) | A case passes when all *required* scorers pass; weights only shape the score |
| [0008](0008-no-baseline-verdict.md) | NO_BASELINE passes with a warning but still enforces absolute rules |
| [0009](0009-deterministic-providers-skip-cassettes.md) | The `mock` provider bypasses cassettes |
| [0010](0010-env-interpolation-for-variants.md) | `${VAR:-default}` interpolation for prompt/model variants and secrets |
| [0011](0011-simulated-model-for-demo.md) | Ship the demo with a clearly labelled simulated model |
| [0012](0012-record-mode-upserts.md) | Record mode upserts; it does not prune stale entries |
| [0013](0013-pass-rate-is-the-gated-metric.md) | Gate on pass rate in percentage points, not mean score |
