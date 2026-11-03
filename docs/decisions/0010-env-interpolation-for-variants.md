# 0010. ${VAR:-default} interpolation for prompt/model variants and secrets

- Status: Accepted
- Date: 2026-11-03

## Context

The demo needs to switch prompt versions, and real projects need to switch base URLs or
model names per environment, without copying configs.

## Decision

After YAML parsing, string values support `${VAR}` and `${VAR:-default}`. A missing variable
with no default is a configuration error naming the variable. API keys are never written
in config; providers read them from the environment variable named by `api_key_env`, only
when a real call is made.

## Consequences

- `TRIAGE_PROMPT=v2_regressed evalgate gate` shows a prompt change without editing files.
- Interpolation happens before validation, so interpolated values are validated too.
- Replay mode never needs the key, so CI does not either.
