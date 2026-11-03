# 0002. The cassette key hashes model + rendered messages + params

- Status: Accepted
- Date: 2026-11-03

## Context

Replay needs a key that identifies "the same request". Options: the golden case id, the
template + inputs, or the fully rendered request.

## Decision

The key is the SHA-256 of canonical JSON (sorted keys, compact separators, UTF-8) of
`{"v": 1, "model", "messages", "params"}`, where `messages` are the fully rendered
system/user messages. The provider name and base URL are not part of the key.

## Consequences

- Any change that could change the answer (prompt wording, a template variable, the
  model name, temperature) is a cache miss. Replay fails loudly with exit code 3 and a
  hint to re-record instead of silently serving a stale answer. This is intended
  behaviour, documented in the guide.
- Identical requests share one recording (for example two judge calls on the same summary).
- Swapping between two OpenAI-compatible gateways that serve the same model name reuses
  recordings. That is usually what you want; use a distinct `model` string if not.
- The `v` field lets the scheme evolve without silently matching old recordings.
