# Presenting EvalGate (FDE / Applied AI roles)

Notes for me, Mourya, on how to present this project. Every number here comes from the
repository's own final run (see the README's *Testing & Evals* section); re-check them if the
code changes.

## 30-second pitch

> Teams change prompts and models every week, and nobody knows if a change made the AI worse
> until a customer complains. I built EvalGate, a regression gate for LLM features: you keep a
> golden set of real cases, EvalGate records the model's answers once, replays them
> deterministically in CI, compares against a baseline, and turns "did this PR make the AI
> worse?" into a red or green check. In the demo, a well-meaning prompt "simplification" drops
> the pass rate from 89.4% to 62.1% and breaks 5 critical cases, like a polite customer who was
> charged twice. The gate blocks the PR and shows exactly which cases flipped.

## 2-minute pitch

1. **Problem (20 s).** LLM features are code that changes behaviour without a diff that explains
   it. Evals exist, but they live in notebooks, run when someone remembers, and nothing enforces
   them. Quality regressions reach users first.
2. **What I built (40 s).** EvalGate is a CLI plus GitHub Action. You describe a suite in YAML:
   the prompt and model, a JSONL golden set, scorers (JSON Schema, label match with confusion
   matrices, regex, an LLM judge, or your own Python), and gate rules: a pass-rate floor, a maximum
   regression in percentage points, a maximum number of cases that flipped from pass to fail, and
   critical tags that must never fail.
3. **The key design choice (30 s).** CI must be deterministic and must not hold API keys. So
   model calls are recorded once into cassettes and replayed. The cassette key is a hash of the
   *rendered* prompt, so any prompt change is a loud cache miss, never a stale answer. The LLM
   judge goes through the same layer, so even rubric grading replays exactly.
4. **Proof (20 s).** The demo is a multilingual support-triage feature for an Indian D2C
   business: 66 hand-written cases in English, Hinglish and Bengali, including sarcasm, prompt
   injection and polite-but-urgent tickets. The "simplified" prompt regresses 27.3 points; all 8
   injection cases and all 5 polite-urgent cases fail. The gate fails on all four rules, and the
   PR comment lists the 18 flipped cases with expected vs actual.
5. **Engineering (10 s).** 172 tests, 99% coverage, `mypy --strict`, friendly errors with a
   documented exit-code contract, 13 ADRs, a runbook.

## 3-minute demo video script

| Time | On screen | Say |
|---|---|---|
| 0:00–0:15 | README top: one-liner and badges | "This is EvalGate, a regression gate for LLM features. Unit tests, but for LLM behaviour." |
| 0:15–0:35 | `examples/support-triage/golden/triage.jsonl` in the editor, scroll to `t011`, `t016`, `t054` | "The feature triages support tickets for an Indian D2C brand: English, Hinglish, Bengali. The golden set has the hard cases: a polite customer who was debited twice, an angry customer complaining about dark mode, and a prompt injection that tries to *lower* the priority of a triple charge." |
| 0:35–0:55 | Side-by-side diff: `prompts/v1.txt` vs `prompts/v2_regressed.txt` | "Here's the PR. Someone simplified the prompt: priority is now 'based on how urgent the customer sounds', and the injection guard is gone. It looks harmless in review." |
| 0:55–1:25 | Terminal: `make demo`; pause on the FAIL table | "EvalGate replays the recorded answers: no API keys, the same answer every time. v1 sets the baseline at 89.4%. The v2 gate fails: 62.1%, minus 27.3 points, 18 flipped cases, and 5 critical cases failing." |
| 1:25–1:50 | `docs/assets/demo-gate-fail.md` rendered on GitHub; expand the flipped cases | "This is the Markdown that lands as a PR comment: rules, flipped cases with expected vs actual, and pass rate by tag. Injection went from 7 of 8 to 0 of 8." |
| 1:50–2:15 | `docs/assets/demo-gate-fail.html` in a browser: confusion matrix, filter "Flipped", open `t054` | "The HTML report is one self-contained file. The priority confusion matrix shows where it breaks; t054 is the injection that talked the model into 'low' on a triple charge." |
| 2:15–2:35 | `evalgate.yaml` → cassette line → `docs/architecture.md` hashing section | "The cassette key hashes the rendered prompt, so changing the prompt forces a re-record. You can't accidentally gate on stale answers. The LLM judge replays through the same layer." |
| 2:35–2:50 | `.github/workflows/evalgate-example.yml` and `action.yml` | "In a real repo it's one action step. It writes the job summary, uploads the HTML, comments on the PR and fails the check." |
| 2:50–3:00 | README Limitations section | "The demo model is simulated, clearly labelled; one command re-records against a real model. That's EvalGate." |

## Résumé bullets

- Built **EvalGate**, an open-source regression gate for LLM features (Python CLI + GitHub
  Action) that records model calls once and replays them deterministically in CI. In a 66-case
  multilingual support-triage demo it caught a prompt regression of 27.3 percentage points
  (89.4% → 62.1%), including 5 failing critical cases, and blocked the PR.
- Designed a cassette layer keyed on SHA-256 of model + rendered prompt + params, with
  record/replay/live modes and an LLM judge routed through the same layer, making CI keyless and
  deterministic; the 66-case demo story runs end to end in about 2 seconds.
- Shipped it to production standards: 172 tests at 99% line coverage (CI floor 90%),
  `mypy --strict`, 10 scorer types, 4 provider types with retry/backoff, PR-comment Markdown and
  self-contained HTML reports, a runbook and 13 architecture decision records.

## Likely interview questions

**1. How do you handle non-determinism?**
Two layers. In CI, I remove it: responses are recorded once and replayed, keyed by a hash of the
rendered request, so the same code always gets the same verdict. Outside CI, I measure it: a
scheduled live run shows drift, and the runbook says to estimate the noise band by repeating
live runs and to set `max_regression` above both that band and one case's worth (1.5 pp for 66
cases). Next on the roadmap is sampling with confidence intervals, so the gate fails only on
statistically significant drops.

**2. Why not just use an existing eval framework?**
Most are platforms: hosted dashboards, databases, tracing. They're great for exploration. The
gap I saw at small teams was enforcement: a check that blocks a PR, is deterministic, needs no
keys in CI, and that one engineer can adopt in an afternoon. EvalGate is deliberately small and
file-based (config, JSONL, a committed baseline). It composes with those tools: the JSON report
can feed a dashboard, and a `python` provider can wrap any pipeline.

**3. How would you deploy this at a customer?**
Week one: sit with the team that owns the feature and pull 50 to 100 real cases from tickets
and logs, deliberately including the failures they already know about. Agree on the output
contract and what "correct" means per field, and tag what must never fail. Record the current
production prompt as the baseline. Add the action to their repo in non-blocking mode
(`fail-on-gate: false`) for a week to show signal without friction, then switch it to blocking.
Every new incident becomes a golden case. Their API keys never leave their own environment
because CI only replays.

**4. How do you know the LLM judge itself is reliable?**
I don't assume it is. The judge is a model, so it gets its own eval: hand-label 30 to 50
outputs, measure judge-human agreement, and only make the judge scorer `required` once agreement
is acceptable. Until then it's tracked but non-gating, which is how the demo configures it. The
rubric is specific and checkable, the scale is a small integer, temperature is 0, the system
prompt tells the judge to ignore instructions inside the graded text, and changing the rubric or
judge model is a cassette miss, so judge changes are reviewed like prompt changes.

**5. Doesn't replaying cassettes mean you never test the real model?**
Replay tests the *change* in the PR against recorded behaviour, which is what a PR gate should
do. The prompt change itself forces a re-record, so the new prompt's answers are real model
answers recorded by the author. What replay can't see is the provider silently changing the
model under the same name; that's a separate, scheduled live job, and its failure means "the
world changed", not "your PR broke it".

**6. Why pass rate and not average score?**
Pass rate reads like a product requirement ("80% of tickets triaged correctly") and a case
passes only when every required check passes, so a valid-JSON-but-wrong-priority answer is a
failure. Weighted averages let an easy check hide a failure on the important one. Mean score is
still reported for context. The trade-off is coarseness on small sets, which I mitigate with
guidance on golden-set size and with the flip count.

**7. What's a "flip" and why gate on it separately?**
A case that passed in the baseline and fails now. Pass rate can stay flat while different cases
break (three fixed, three broken). Flips catch that, and they're the most actionable part of
the report: each one is a concrete regression with expected vs actual.

**8. How did you build a realistic demo without API keys?**
I wrote a deterministic simulated model that reads the rendered prompt the way a model would:
with the good prompt it follows the priority rules and ignores injected instructions; with the
simplified prompt it lets tone drive priority and obeys injections. It also has generic
weaknesses (sarcasm read as praise, anchoring on the first issue), so v1 is good but not
perfect. Its answers are recorded through the normal record mode. It's labelled as simulated
everywhere, and there's a ready-made config to re-record against a real model.

**9. What would you build next?**
Statistical significance for noisy evals, cost and latency gating (the data is already in the
cassettes), and dataset versioning so deltas compare only shared cases. After that, RAG and
agent-trajectory scorers, because that's where most production features are heading.

**10. What was the hardest design trade-off?**
What goes into the cassette key. Hashing only the case id would survive prompt edits but would
silently replay answers to an old prompt, which is the worst failure for a gate. Hashing the
rendered request makes prompt changes cost a re-record. I chose correctness and made the miss
loud and actionable: exit 3, the suite name, and the exact command to re-record.

## How this maps to the FDE job

- **Working with a customer's messy LLM feature.** Real features are prompts plus glue code
  plus retrieval. The `python` provider wraps an entire pipeline as a black box, and the golden
  set format (template inputs + expected fields + tags + notes) fits whatever the customer
  already has. The demo deliberately includes the mess: code-mixed languages, sarcasm, two
  issues in one ticket, and injections.
- **Defining success metrics with them.** The config *is* the metric agreement:
  `min_pass_rate`, `max_regression`, `critical_tags`. Writing it forces the useful conversation:
  "which mistakes are unacceptable?", "how much regression is acceptable for a faster model?".
  `notes` on golden cases record why a label is what it is.
- **Making quality visible to non-engineers.** The PR comment and the HTML report are written
  for a support lead or PM: plain-language rule results, per-tag pass rates ("Hinglish dropped
  19 points"), and concrete examples of what broke. The baseline update is a reviewed diff, so
  accepting lower quality is an explicit decision someone signs off.
- **Shipping inside their constraints.** No keys in CI, no database, no new service to run;
  it installs with pip or Docker and runs in whatever CI they have.

## LinkedIn launch post (draft)

> I built EvalGate, an open-source regression gate for LLM features.
>
> Teams change prompts and models all the time, and quality regressions usually reach users
> before anyone notices. EvalGate runs a golden set of real cases against your prompt, compares
> the results to a stored baseline, and fails the pull request when quality drops.
>
> CI stays deterministic and needs no API keys: model answers (including LLM-judge grades) are
> recorded once and replayed. Changing the prompt forces a re-record, so the gate never grades
> stale answers.
>
> The demo is a support-ticket triage feature for an Indian D2C brand, with 66 cases in
> English, Hinglish and Bengali. A "simplified" prompt drops the pass rate from 89.4% to 62.1%,
> fails every prompt-injection case, and misses 5 critical tickets, like a customer who was
> charged twice but asked politely. The gate blocks it and the PR comment shows each case that
> broke. (The demo uses a clearly labelled simulated model so it runs offline.)
>
> Python, Typer, Pydantic, httpx; 172 tests, 99% coverage, a GitHub Action.
>
> Repo: https://github.com/mourya-dasgupta/evalgate
>
> Feedback welcome, especially from teams running evals in CI.

## X / Twitter thread (draft)

1. I built EvalGate: a regression gate for LLM features. Unit tests, but for LLM behaviour.
   Golden set → record once → replay in CI → compare to baseline → red/green check on every PR.
   https://github.com/mourya-dasgupta/evalgate
2. The core idea: CI must be deterministic and keyless. Model calls are recorded into
   "cassettes" keyed by a hash of the rendered prompt. Change the prompt and it's a loud miss,
   not a stale answer. The LLM judge replays through the same layer.
3. Demo: support triage for an Indian D2C brand, 66 cases in English, Hinglish and Bengali. A
   "simplified" prompt: 89.4% → 62.1%, 0/8 prompt-injection cases, 5 critical tickets missed. The
   gate fails and the PR comment lists all 18 flipped cases.
4. Gate rules: pass-rate floor, max regression in percentage points, max flipped cases, and
   critical tags that must never fail. Exit codes distinguish "AI got worse" from "config
   broken" from "provider down".
5. Small on purpose: files in git, no database, no dashboard. 172 tests, 99% coverage,
   mypy --strict. The demo model is simulated (labelled); one command re-records with a real one.

## GitHub repository settings

**Pinned-repo description (≤ 350 chars):**

> Regression gate for LLM features: golden-set evals that record model answers once, replay them deterministically in CI, compare to a baseline, and fail the PR when quality drops. CLI + GitHub Action, LLM judge, multilingual demo.

**Topics:** `llm`, `evals`, `llm-evaluation`, `prompt-engineering`, `regression-testing`,
`ci`, `github-actions`, `golden-dataset`, `llm-as-a-judge`, `python`, `mlops`, `ai-quality`.
