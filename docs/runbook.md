# Runbook: what to do when it breaks

Each section: symptom → diagnosis → fix. Exit codes: `1` gate failed, `2` config/usage
error, `3` provider/cassette error.

## The gate fails unexpectedly

**Symptom.** A PR that "shouldn't affect the AI" fails EvalGate (exit 1).

1. Open the job summary (Markdown report) or download the HTML report artifact. Look at
   the **failed rules** and the **flipped cases**: each flip shows expected vs actual and the
   scorer's reason.
2. Check whether the PR touched anything in the request: the prompt template, a shared
   snippet included in the prompt, model name, params, the golden set, or code in a `python`
   provider. Any of these legitimately changes behaviour.
3. Check the **per-tag table**. A drop concentrated in one tag (`injection`, `hinglish`) points
   at a specific behaviour, not noise.
4. Reproduce locally (replay is deterministic):

   ```bash
   evalgate gate --verbose
   evalgate report --format html --output report.html
   ```

5. Decide:
   - **Real regression** → fix the prompt/code, re-record if the request changed, push.
   - **Intended trade-off** (for example, better on billing, slightly worse on sarcasm) →
     update the baseline in the PR so a reviewer approves it explicitly:
     `evalgate baseline update`, commit `.evalgate/baseline.json`.
   - **Wrong expectation in the golden set** → fix the case (with a `notes` explanation),
     re-run, update the baseline.
6. If the warning says *golden set changed since the baseline*, the delta compares different
   case sets. Update the baseline in the same PR that changes the golden set.

## Cassette miss in CI

**Symptom.** Exit 3, `Cassette miss: no recording for this request … Re-record with: evalgate --mode record run --suite NAME`.

**Cause.** The request hash changed: prompt text, a template variable, a golden-set input,
the model name or params. Replay refuses to serve an answer recorded for a different request.

**Fix.**

```bash
export OPENAI_API_KEY=...          # or the provider's key
evalgate --mode record run --suite NAME
evalgate gate                      # replay locally to confirm
git add cassettes/NAME.jsonl && git commit -m "eval: re-record NAME after prompt change"
```

If the change was not supposed to alter the prompt (for example whitespace in a template),
`git diff` the rendered request in the cassette (`request.messages`) against the new prompt
to find what moved. Avoid non-deterministic template content (dates, random ids) in prompts.

## The provider rate-limits

**Symptom.** Recording or live runs end with exit 3: `giving up after N attempt(s): HTTP 429`.

**Fix.** EvalGate already retries 429/5xx with exponential backoff and honours
`Retry-After`. If that is not enough:

```yaml
settings:
  concurrency: 2        # fewer parallel calls
  max_retries: 6
  backoff_base_s: 2     # 2s, 4s, 8s, ...
```

Record one suite at a time (`--suite NAME`). Recording upserts, so re-running after a
partial failure only costs the calls you repeat. The cassette is saved even when some cases
fail. Replay mode never calls the provider and cannot be rate-limited.

## The baseline is corrupted

**Symptom.** Exit 2, `baseline .evalgate/baseline.json is corrupted or not an EvalGate run`.
`gate` checks the baseline before running anything.

**Fix (preferred): restore from git.**

```bash
git log --oneline -- .evalgate/baseline.json   # find the last good commit
git checkout HEAD~1 -- .evalgate/baseline.json   # or use the hash from the log
```

**Fix: rebuild it** from a known-good state of the prompt (for example `main`):

```bash
git stash                                # or check out main
evalgate run
evalgate baseline update
git stash pop
```

Merge conflicts in `baseline.json` are the most common cause. Never hand-merge it: take one
side and rebuild with the commands above.

## Flaky results in live mode

**Symptom.** `evalgate --mode live gate` passes and fails on the same code.

**Cause.** Live mode is non-deterministic by nature: sampling, provider-side model updates,
load-dependent batching. That is why CI uses replay.

**Fix.**

- Keep PR gating in **replay** mode; use live mode for scheduled drift checks only.
- Use `temperature: 0` (and a `seed` param where the provider supports it).
- Measure the noise: run live several times and compare pass rates. Set `max_regression` above
  that noise band and above one case's worth (100 / number of cases, in pp).
- Grow the golden set; noise in pass rate shrinks with more cases.
- If one or two cases flip-flop, they are ambiguous: tighten the expected answer or the prompt,
  or mark the scorer `required: false` while you investigate.
- For a judge scorer, check judge-human agreement before making it `required` (see the guide).

## Roll back a baseline

The baseline is a committed file, so rollback is a git operation:

```bash
git log --oneline -- .evalgate/baseline.json        # find the last good version
git checkout HEAD~1 -- .evalgate/baseline.json      # or use the hash from the log
evalgate baseline show                              # confirm what it contains
git commit -m "eval: roll back baseline"
```

Or promote a specific saved run (runs live in `.evalgate/runs/`, newest last):

```bash
ls .evalgate/runs/                                   # file names are UTC timestamps
evalgate baseline update --run "$(ls .evalgate/runs/*.json | tail -n 2 | head -n 1)"   # the run before the latest
```

To roll back a single suite and keep the others, add `--suite NAME` to the same command.

## Config or golden-set errors (exit 2)

Run `evalgate validate`. It reports every problem at once, with the field path for config
errors (`suites[0](triage).gate.min_pass_rate`) and line numbers for golden-set errors, and it
renders every case through the template so missing variables surface before any API call.
