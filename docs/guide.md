# EvalGate user guide

EvalGate runs golden-set evaluations against a prompt + model, compares the results to a
stored baseline, and fails CI when quality drops. This guide covers everything: install,
concepts, every command, every config field, how to write good golden sets and custom
scorers, how to record with a real model, CI setup, and troubleshooting.

- [Installation](#installation)
- [Concepts](#concepts)
- [Commands](#commands)
- [Configuration reference](#configuration-reference)
- [Scorers](#scorers)
- [Writing good golden sets](#writing-good-golden-sets)
- [Writing a custom scorer](#writing-a-custom-scorer)
- [Recording with a real model](#recording-with-a-real-model)
- [CI setup](#ci-setup)
- [Troubleshooting](#troubleshooting)

## Installation

EvalGate needs Python 3.11 or newer.

```bash
pip install "git+https://github.com/mourya-dasgupta/evalgate.git"
```

From a clone (for development):

```bash
git clone https://github.com/mourya-dasgupta/evalgate.git
cd evalgate
pip install -e ".[dev]"
```

Check it works:

```bash
evalgate --version
```

Docker (no Python needed on the host):

```bash
docker build -t evalgate .
docker run --rm -u "$(id -u):$(id -g)" -v "$PWD:/work" evalgate gate
```

## Concepts

| Concept | What it is |
|---|---|
| **Suite** | One LLM feature under test: a *target* (provider + model + prompt template), a *golden set*, *scorers* and *gate rules*. A config can have many suites. |
| **Golden set** | A JSONL file of test cases. Each case has an `id`, the template variables (`input`), what a correct answer looks like (`expected`), and optional `tags` and `notes`. |
| **Scorer** | A check that grades one output and returns a score in [0, 1] plus a reason. A case **passes** when every *required* scorer meets its threshold. |
| **Run** | One execution of one or more suites. Saved as `.evalgate/runs/<timestamp>.json`. |
| **Baseline** | A run you have promoted as "known good" (`.evalgate/baseline.json`). Commit it. |
| **Gate** | Rules that compare the current run to the baseline (and to absolute floors) and produce a verdict: `PASS`, `FAIL` or `NO_BASELINE`. |
| **Flip** | A case that passed in the baseline and fails now. The most actionable signal in a report. |
| **Cassette** | A JSONL file (`cassettes/<suite>.jsonl`) of recorded model responses keyed by a hash of the request. CI replays cassettes, so it is deterministic and needs no API keys. |

### Modes

| Mode | Behaviour |
|---|---|
| `replay` (default) | Serve every model call from the cassette. A request that was never recorded is a *cassette miss*: exit code 3 with a hint to re-record. |
| `record` | Call the real provider and save (upsert) each response into the cassette. |
| `live` | Call the real provider; never read or write cassettes. For exploration and drift checks. |

The cassette key is a SHA-256 of the model name, the **fully rendered** messages and the
request params. Any prompt change, template-variable change, model change or parameter
change is therefore a miss in replay mode and must be re-recorded. That is deliberate:
replaying an answer to a different prompt would make the gate lie. See
[architecture.md](architecture.md#cassette-hashing-scheme).

The `mock` provider is deterministic and never uses cassettes.

### Verdicts and exit codes

| Exit code | Meaning |
|---|---|
| `0` | Gate passed, or `NO_BASELINE` (passes with a warning) |
| `1` | Gate failed |
| `2` | Configuration or usage error (bad YAML, invalid golden set, unknown suite, corrupted baseline, …) |
| `3` | Provider or cassette error (cassette miss, missing API key, rate limit after retries, malformed response) |

## Commands

Global options can be given before or after the command:

| Option | Meaning |
|---|---|
| `--config, -c PATH` | Config file (default `evalgate.yaml` in the current directory) |
| `--mode, -m replay\|record\|live` | Provider mode (default `replay`; also settable with `EVALGATE_MODE`) |
| `--verbose, -v` | More detail; full flip lists; tracebacks for unexpected errors |
| `--version` | Print the version |

### `evalgate init`

Scaffolds a runnable starter project in the current directory (or `--dir PATH`):
`evalgate.yaml`, `prompts/sentiment.txt`, `golden/sentiment.jsonl` (10 cases),
`.github/workflows/evalgate.yml` and `.evalgate/.gitignore`. Existing files are skipped
unless you pass `--force`. The starter uses the `mock` provider, so it runs offline.

```bash
evalgate init
evalgate init --dir my-feature --force
```

### `evalgate validate`

Checks the config, golden sets (with line numbers), prompt templates (every case is
rendered, so a missing variable is caught before any API call) and scorer options. Prints
per-suite case and tag counts and warnings (unused input keys, critical tags no case uses,
very small golden sets). Exits 2 if anything is invalid.

```bash
evalgate validate
evalgate validate --suite triage
```

### `evalgate run`

Runs all suites (or `--suite NAME`, repeatable), prints the results table, and writes
`.evalgate/runs/<timestamp>.json`. It does not gate (exit 0), except that it exits 3 if any
case could not get a model response.

```bash
evalgate run
evalgate run --suite triage
evalgate --mode record run          # call the real provider and record cassettes
```

### `evalgate gate`

Runs, compares to the baseline, prints a verdict and exits non-zero on failure. Optionally
writes reports:

```bash
evalgate gate
evalgate gate --suite triage --report-md report.md --report-html report.html --report-json report.json
```

### `evalgate baseline update`

Promotes the latest run (or `--run FILE`) to `.evalgate/baseline.json`. With `--suite`,
only those suites are replaced and the rest of the baseline is kept. Runs that contain
errored cases are refused.

```bash
evalgate baseline update
evalgate baseline update --suite triage
evalgate baseline update --run .evalgate/runs/2026-11-03T06-52-12-427491Z.json
```

Commit the baseline file. Updating it in a PR makes "we accept this new level of quality"
an explicit, reviewed decision.

### `evalgate baseline show`

Prints what the current baseline contains (run id, suites, models, prompts, pass rates).

```bash
evalgate baseline show
```

### `evalgate report`

Renders the latest run (or `--run FILE`), compared to the baseline if there is one, as
Markdown (PR comment), a self-contained HTML file, or JSON. Writes to stdout or `--output`.

```bash
evalgate report --format md
evalgate report --format html --output report.html
evalgate report --format json --run .evalgate/runs/2026-11-03T06-52-12-427491Z.json
```

## Configuration reference

```yaml
version: 1                       # optional, currently always 1

settings:                        # all optional
  concurrency: 8                 # parallel model calls per suite (1-256)
  timeout_s: 60                  # per-request timeout
  max_retries: 3                 # retries on 408/409/425/429/5xx/529, timeouts, network errors
  backoff_base_s: 1.0            # exponential backoff: 1s, 2s, 4s… (Retry-After is honoured, max 60s)
  cassette_dir: cassettes        # cassettes/<suite>.jsonl
  runs_dir: .evalgate/runs
  baseline_path: .evalgate/baseline.json

suites:
  - name: triage                 # letters, digits, '.', '_', '-'
    description: optional text shown in reports
    concurrency: 4               # optional per-suite override
    target:
      provider: openai_compatible   # mock | openai_compatible | anthropic | python
      model: gpt-4o-mini
      prompt: prompts/v1.txt        # Jinja2 template; case `input` keys are the variables
      system_prompt: prompts/system.txt   # optional, also a template
      base_url: https://api.openai.com/v1 # default per provider
      api_key_env: OPENAI_API_KEY         # default per provider; "none" for no auth
      params: {temperature: 0, max_tokens: 300}   # passed through to the API
      timeout_s: 30                       # optional per-target override
    golden: golden/triage.jsonl
    scorers:
      - type: json_valid
      - type: label_match
        field: priority
        weight: 2                # weight in the case score (default 1)
        required: true           # must pass for the case to pass (default true)
        threshold: 1.0           # score needed to pass (default 1.0)
        name: priority           # optional display name (default "type:field" or type)
    gate:
      min_pass_rate: 0.8         # absolute floor, 0-1
      max_regression: 5          # max pass-rate drop vs baseline, in percentage points
      max_new_failures: 3        # max flips (passed in baseline, failing now)
      critical_tags: [critical]  # any failing case with one of these tags fails the gate
```

All paths are relative to the config file's directory, so `evalgate --config
path/to/evalgate.yaml gate` works from anywhere.

**Environment variables.** Any string value may use `${VAR}` or `${VAR:-default}`, for
example `prompt: prompts/${PROMPT_VERSION:-v1}.txt` or `base_url: ${LLM_BASE_URL}`. A
referenced variable that is unset and has no default is a configuration error. Never put
API keys in the config; name the variable with `api_key_env`.

### Providers

| `provider` | Fields | Notes |
|---|---|---|
| `mock` | `mock_responses: [{match: <regex>, respond: <text>}]`, `mock_default` | First rule whose regex matches the user message wins. Deterministic; never cassetted. |
| `openai_compatible` | `base_url` (default `https://api.openai.com/v1`), `api_key_env` (default `OPENAI_API_KEY`) | `POST {base_url}/chat/completions`. Works with OpenAI, Azure-style gateways, Groq, Together, vLLM, Ollama, LiteLLM… `params` are merged into the body. |
| `anthropic` | `base_url` (default `https://api.anthropic.com`), `api_key_env` (default `ANTHROPIC_API_KEY`) | `POST {base_url}/v1/messages`. `system_prompt` becomes the `system` field; `params.max_tokens` defaults to 1024. |
| `python` | `entrypoint: module:ClassName` | Your own Python object with `complete(request)` (sync or async) returning a string or `ChatResponse`. The module is imported from the config directory. Use it to evaluate a whole pipeline (RAG, tools) instead of a single call. Cassetted like a real provider. |

HTTP providers retry 408/409/425/429/500/502/503/504/529, timeouts and network errors
`max_retries` times with exponential backoff (honouring `Retry-After`). Other 4xx errors
fail immediately with a hint (for 401/403: check the key; for 404: check `base_url` and
`model`). Requests run concurrently up to `concurrency`.

### Golden set format

One JSON object per line:

```json
{"id": "t011", "input": {"message": "₹2,350 was debited twice…"}, "expected": {"category": "billing", "priority": "urgent"}, "tags": ["polite-urgent", "critical"], "notes": "Polite tone, but a double debit is urgent."}
```

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Unique, stable id. Flips are tracked by id, so do not reuse ids for different cases. |
| `input` | yes | Object of template variables. |
| `expected` | yes | Any JSON value: a string, a number, or an object whose fields scorers read with `field`. Use `null` if no reference exists (for example judge-only suites). |
| `tags` | no | List of strings. Used for per-tag pass rates and `critical_tags`. |
| `notes` | no | Why the case exists. Shown in the HTML report. |

Blank lines are ignored. Every invalid line is reported with its line number in one go.

## Scorers

Every scorer accepts `weight`, `required`, `threshold` and `name` (see above). Scorers that
read part of a JSON output accept:

- `field`: dotted path into the JSON-parsed output (`category`, `items.0.name`). Markdown code
  fences around JSON are tolerated.
- `expected_field`: dotted path into `expected`. Defaults to `field` when `expected` is an object.

| Type | Options | Score |
|---|---|---|
| `exact_match` | `field`, `expected_field`, `case_sensitive` (true), `normalize_whitespace` (true), `strip` (true) | 1 if equal after normalisation |
| `contains` | `values` (string or list; default: `expected`), `case_sensitive` (false), `mode` (`all`/`any`), `field` | fraction of values found (`all`) or 1/0 (`any`) |
| `not_contains` | `values`, `case_sensitive` (false), `field` | 1 if none of the values appear |
| `regex` | `pattern`, `ignore_case` (false), `full_match` (false), `field` | 1 if the pattern matches |
| `json_valid` | `allow_code_fences` (true), `require_object` (false) | 1 if the output parses as JSON |
| `json_schema` | `schema` (inline) **or** `schema_path`, `field` | 1 if valid against the JSON Schema; reason names the first violation |
| `numeric_tolerance` | `tolerance` (absolute), `relative` (fraction), `field`, `expected_field` | 1 if the first number in the output is within tolerance |
| `label_match` | `field`, `expected_field`, `labels` (allowed set), `case_sensitive` (false) | 1 if the label matches. Suites get a **confusion matrix** per `label_match` scorer. |
| `llm_judge` | `rubric`, `judge` (a provider block), `field`, `include_expected` (true), `min_score` (1), `max_score` (5) | judge's score normalised to 0-1 |
| `custom` | `path` (`module:function` or `module:Class`), `options` (dict) | whatever your code returns |

### LLM judge

```yaml
- type: llm_judge
  name: summary_quality
  field: summary
  required: false        # track it without gating on it until you trust it
  threshold: 0.75        # 4/5 or better
  rubric: >-
    The summary is one English sentence that states the customer's actual problem.
  judge:
    provider: anthropic
    model: claude-haiku-5-5
    params: {max_tokens: 200}
```

The judge request goes through the same provider and cassette layer as the target, so
judge verdicts are recorded and replayed too. It defaults to `temperature: 0`, and the
system prompt tells the judge to ignore instructions inside the graded output.

**Is the judge reliable?** Treat it as a model that needs its own eval. Before you make a
judge scorer `required`, hand-label 30–50 outputs, run the judge on them, and check agreement
(for example, the share of cases where judge and human agree on pass/fail). Keep the rubric
specific and checkable, prefer a small integer scale, and re-check agreement when you change
the judge model or the rubric (both are cassette misses, so you will notice).

## Writing good golden sets

**How many cases.** Pass rate is coarse on small sets: with 20 cases one case is 5 pp. Aim
for **30-100 cases per suite** to start, and set `max_regression` above one case's worth
(for 66 cases one case is ~1.5 pp, so `5` tolerates three flips' worth of noise). Grow the set
from production: every bug report about the feature should become a case.

**Coverage.** Cover the input distribution *and* the failure modes:

- the common, boring cases (they are most of your traffic);
- every output class (each category, each priority level);
- each language or script your users write in (the demo mixes English, Hinglish and Bengali
  in Latin script);
- adversarial inputs: prompt injection, delimiter break-outs, instructions that try to
  *lower* severity;
- cases where surface signals mislead: polite-but-urgent, angry-but-trivial, sarcasm,
  two issues in one message;
- empty, very long, or malformed inputs if they can reach production.

**Tagging strategy.** Tags power the per-tag table, the most useful view in a regression
report. Use a few orthogonal families:

- *risk*: `critical` for cases that must never fail (money, security, safety). Wire it into
  `critical_tags`.
- *phenomenon*: `injection`, `sarcasm`, `multi-issue`, `polite-urgent`, `angry-low`.
- *segment*: `hinglish`, `bengali`, `b2b`.

**Expected values.** Prefer structured outputs and structured expectations
(`{"category": ..., "priority": ...}`) checked with `label_match` / `json_schema`, over free
text checked by a judge. Write `notes` for every non-obvious case: the next person to
disagree with a label will thank you.

**Stable ids.** Never renumber. Flips are tracked by id.

## Writing a custom scorer

Put a module next to `evalgate.yaml` (it is importable from the config directory):

```python
# my_scorers.py
from evalgate.golden import GoldenCase
from evalgate.scorers import ScoreResult


def summary_mentions_amount(output: str, case: GoldenCase, options: dict) -> ScoreResult:
    """Pass if the summary repeats the rupee amount from the message."""
    import json
    import re

    amount = re.search(r"₹[\d,]+", case.input["message"])
    if amount is None:
        return ScoreResult(1.0, "no amount in the message")
    summary = json.loads(output).get("summary", "")
    if amount.group(0) in summary:
        return ScoreResult(1.0, f"mentions {amount.group(0)}")
    return ScoreResult(0.0, f"summary does not mention {amount.group(0)}")
```

```yaml
scorers:
  - type: custom
    name: mentions_amount
    path: my_scorers:summary_mentions_amount
    required: false
    options: {}            # passed as the third argument
```

A custom scorer function may take `(output, case)` or `(output, case, options)`, may be
`async`, and may return a `ScoreResult`, a float, a bool, or a `(score, reason)` tuple. For
reusable scorers with validated options, subclass `Scorer`:

```python
from evalgate.scorers import Scorer, ScorerOptions, ScoreResult


class MaxLengthOptions(ScorerOptions):
    max_chars: int = 200


class MaxLength(Scorer):
    Options = MaxLengthOptions

    def score_sync(self, output, case):
        ok = len(output) <= self.options.max_chars
        return ScoreResult(1.0 if ok else 0.0, f"{len(output)} chars")
```

```yaml
  - type: custom
    path: my_scorers:MaxLength
    options: {max_chars: 300}
```

If a custom scorer raises, the case gets score 0 for that scorer with the exception as the
reason; the run continues.

## Recording with a real model

**OpenAI-compatible endpoint:**

```yaml
target:
  provider: openai_compatible
  model: gpt-4o-mini
  api_key_env: OPENAI_API_KEY
  prompt: prompts/v1.txt
  params: {temperature: 0, max_tokens: 300}
```

```bash
export OPENAI_API_KEY=sk-...
evalgate --mode record run      # calls the API, writes cassettes/<suite>.jsonl
evalgate baseline update
git add cassettes .evalgate/baseline.json && git commit -m "eval: record baseline"
evalgate gate                   # replay: no API calls, no key needed
```

**Anthropic:**

```yaml
target:
  provider: anthropic
  model: claude-haiku-5-5
  api_key_env: ANTHROPIC_API_KEY
  prompt: prompts/v1.txt
  system_prompt: prompts/system.txt
  params: {temperature: 0, max_tokens: 300}
```

```bash
export ANTHROPIC_API_KEY=sk-ant-...
evalgate --mode record run
```

**When you change a prompt in a PR:** record the new responses in the same PR
(`evalgate --mode record run --suite NAME`), commit the cassette, and let CI gate in replay.
If quality changes on purpose, also run `evalgate baseline update` and commit the baseline;
reviewers see both diffs.

The support-triage example ships `evalgate.real.yaml`, a ready-made real-model config with
separate cassettes and baseline; see `examples/support-triage/README.md`.

## CI setup

### GitHub Actions

```yaml
# .github/workflows/evalgate.yml
name: EvalGate
on: [pull_request]
permissions:
  contents: read
jobs:
  evalgate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: mourya-dasgupta/evalgate@main   # pin to a release tag once published
        with:
          config: evalgate.yaml
          # working-directory: services/triage
          # suite: triage            # space-separated; default all
```

The action installs EvalGate, runs `evalgate gate` in replay mode, appends the Markdown
report to the job summary, uploads the HTML report as an artifact, and fails the job if the
gate fails. Outputs: `verdict`, `exit-code`, `report-md`, `report-html`. To post the report as
a sticky PR comment, see
[`.github/workflows/evalgate-example.yml`](../.github/workflows/evalgate-example.yml).

| Input | Default | Meaning |
|---|---|---|
| `config` | `evalgate.yaml` | Config path, relative to `working-directory` |
| `working-directory` | `.` | Where to run |
| `suite` | (all) | Space-separated suite names |
| `mode` | `replay` | `replay`, `record` or `live` (the last two need API keys as env vars) |
| `python-version` | `3.12` | Python to install |
| `evalgate-version` | (action's own) | pip requirement, e.g. `evalgate==0.1.0` |
| `report-name` | `evalgate-report` | Artifact name |
| `fail-on-gate` | `true` | Set `false` to report without failing the job |

### Other CI systems

Any CI that runs Python works:

```bash
pip install "git+https://github.com/mourya-dasgupta/evalgate.git"
evalgate gate --report-md evalgate-report.md --report-html evalgate-report.html
```

Or use the Docker image (see [Installation](#installation)).

### A nightly drift check

Replay never notices a provider silently changing a model. Add a scheduled job that runs
`evalgate --mode live gate` with the API key as a secret; a failure there means the world
changed, not your code.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Configuration error: config file not found: evalgate.yaml` | Run from the project directory, pass `--config`, or run `evalgate init`. |
| `… has N problem(s): suites[0](triage).gate.min_pass_rate: …` | The message names the exact field. Fix it there. Valid fields are listed in this guide. |
| `golden.jsonl has N invalid line(s): line 12: …` | Fix the listed lines. Each line must be a JSON object with `id`, `input`, `expected`. |
| `could not render for case 't007': 'message' is undefined` | The template uses a variable the case `input` lacks. `evalgate validate` lists every such case. |
| Exit 3: `no recording for this request` | Cassette miss: the prompt, model or params changed. Re-record: `evalgate --mode record run --suite NAME`, commit the cassette. See the [runbook](runbook.md#cassette-miss-in-ci). |
| Exit 3: `environment variable OPENAI_API_KEY is not set` | Only record/live modes need keys. Export the key, or use replay. |
| Exit 3: `giving up after 4 attempt(s): HTTP 429` | Rate limited. Lower `settings.concurrency`, raise `max_retries` / `backoff_base_s`. See the [runbook](runbook.md#the-provider-rate-limits). |
| `baseline … is corrupted` | Restore it from git (`git checkout -- .evalgate/baseline.json`) or rebuild it. See the [runbook](runbook.md#the-baseline-is-corrupted). |
| Gate fails with `golden set changed since the baseline` warning | You added or removed cases; the delta compares different sets. Update the baseline in the same PR if the change is intended. |
| A custom scorer always scores 0 | Its reason will say `scorer raised …`. Run with `--verbose` and fix the exception. |
| `could not import module …` | Custom scorer/provider modules are imported from the config directory. Check the file name and the `module:name` path. |

For incident-style procedures (unexpected gate failures, flaky live runs, rolling back a
baseline) see the [runbook](runbook.md).
