# Issues to create

Ten issues drawn from the [roadmap](roadmap.md). Each has a title, context, acceptance
criteria and labels. All ten have been created on GitHub as
[issues #1–#10](https://github.com/mourya-dasgupta/evalgate/issues); this file keeps the
drafts alongside the code.

---

## 1. Gate on statistical significance for noisy evals

**GitHub:** [#1](https://github.com/mourya-dasgupta/evalgate/issues/1)

**Labels:** `enhancement`, `gate`, `roadmap:now`

**Context.** Pass rate on a 60-case suite moves ~1.7 pp per case. With live sampling, two
runs of the same prompt can differ by several points. Gating on a fixed `max_regression`
either flaps or is too loose.

**Acceptance criteria**
- [ ] New suite option `samples: N` runs each case N times (live/record) or replays N recorded samples.
- [ ] Runs store per-case pass frequency; suite metrics include a 95% confidence interval for pass rate.
- [ ] New gate rule `regression_significance: 0.05` fails only when the drop vs baseline is statistically significant (two-proportion test or bootstrap).
- [ ] Reports show the interval next to the pass rate.
- [ ] Documented in the guide with guidance on choosing N.

---

## 2. Track cost and latency per run, with gate rules

**GitHub:** [#2](https://github.com/mourya-dasgupta/evalgate/issues/2)

**Labels:** `enhancement`, `reports`, `gate`, `roadmap:now`

**Context.** Providers return token usage; cassettes already store usage and latency. A
prompt change that doubles tokens is a regression even when accuracy holds.

**Acceptance criteria**
- [ ] Runs aggregate input/output tokens and p50/p95 latency per suite.
- [ ] Optional per-model price table in config produces an estimated cost per run.
- [ ] Gate rules `max_cost_increase_pct` and `max_p95_latency_ms`.
- [ ] Terminal, Markdown and HTML reports show cost and latency with deltas.

---

## 3. First-class PR comment from the GitHub Action

**GitHub:** [#3](https://github.com/mourya-dasgupta/evalgate/issues/3)

**Labels:** `enhancement`, `github-action`, `roadmap:now`

**Context.** The example workflow posts the Markdown report with `actions/github-script`.
Every user has to copy that block.

**Acceptance criteria**
- [ ] Action input `comment: true` creates or updates one sticky comment (identified by a hidden marker).
- [ ] Skips gracefully (with a log line) on fork PRs without write permission.
- [ ] Comment is truncated safely below GitHub's 65,536-character limit with a link to the artifact.
- [ ] Documented in the guide's CI section.

---

## 4. `evalgate cassette prune`

**GitHub:** [#4](https://github.com/mourya-dasgupta/evalgate/issues/4)

**Labels:** `enhancement`, `cli`, `cassettes`, `roadmap:now`

**Context.** Record mode upserts by design (ADR 0012), so recordings for old prompt versions accumulate.

**Acceptance criteria**
- [ ] `evalgate cassette prune [--suite NAME] [--keep-env VAR=a,b]` computes every request the current config can produce (optionally for several env-var variants) and removes the rest.
- [ ] `--dry-run` lists what would be removed.
- [ ] Never removes judge entries that are still reachable.
- [ ] Tests cover multi-variant suites like the support-triage demo.

---

## 5. Version golden sets and compare only shared cases

**GitHub:** [#5](https://github.com/mourya-dasgupta/evalgate/issues/5)

**Labels:** `enhancement`, `compare`, `roadmap:next`

**Context.** When cases are added or removed, the pass-rate delta compares different sets.
EvalGate warns today but cannot correct for it.

**Acceptance criteria**
- [ ] Runs record a golden-set content hash and per-case content hashes.
- [ ] Comparison reports both the overall delta and the delta on cases present in both runs (unchanged content).
- [ ] `max_regression` uses the shared-case delta when the set changed; this is reported explicitly.
- [ ] A case whose `expected` changed is treated as new, not as a flip.

---

## 6. RAG scorers: faithfulness and context recall

**GitHub:** [#6](https://github.com/mourya-dasgupta/evalgate/issues/6)

**Labels:** `enhancement`, `scorers`, `roadmap:next`

**Context.** Retrieval pipelines fail by answering from outside the retrieved context, or by
not retrieving the needed passage.

**Acceptance criteria**
- [ ] `python` providers can return structured responses (`text` + `context: list[str]`), stored in cassettes.
- [ ] `faithfulness` scorer (LLM-judge-based, replayable) checks every claim is supported by context.
- [ ] `context_recall` scorer checks expected facts/passages appear in retrieved context (string and judge modes).
- [ ] Example suite under `examples/` with a toy retriever.

---

## 7. Multi-turn and agent trajectory evals

**GitHub:** [#7](https://github.com/mourya-dasgupta/evalgate/issues/7)

**Labels:** `enhancement`, `golden-sets`, `scorers`, `roadmap:next`

**Context.** Chat assistants and agents regress mid-conversation: wrong tool, wrong
arguments, loops.

**Acceptance criteria**
- [ ] Golden cases may contain `messages` (conversation history) instead of template `input`.
- [ ] `python` providers can return a trajectory (tool calls with arguments, final answer).
- [ ] Scorers `tool_called`, `tool_args_match` and `max_steps` operate on trajectories.
- [ ] HTML report renders the trajectory per case.

---

## 8. pytest plugin mode

**GitHub:** [#8](https://github.com/mourya-dasgupta/evalgate/issues/8)

**Labels:** `enhancement`, `integration`, `roadmap:next`

**Context.** Many teams already gate on pytest and would rather not add another CI step.

**Acceptance criteria**
- [ ] `pip install evalgate[pytest]` registers a plugin; `pytest --evalgate` collects one test per suite (optionally per case).
- [ ] Gate failures fail the test with the Markdown summary as the failure message.
- [ ] Respects `--evalgate-mode` and `--evalgate-config`.

---

## 9. Static trend dashboard from committed results

**GitHub:** [#9](https://github.com/mourya-dasgupta/evalgate/issues/9)

**Labels:** `enhancement`, `reports`, `roadmap:later`

**Context.** Quality should be visible to non-engineers over time, without adding a database.

**Acceptance criteria**
- [ ] `evalgate dashboard --out site/` walks git history of the baseline file(s) and writes a static HTML site.
- [ ] Shows pass rate per suite and per tag over time, with the commit and PR that changed each baseline.
- [ ] Self-contained (no external assets), deployable to GitHub Pages.

---

## 10. MCP server so coding agents can run evals

**GitHub:** [#10](https://github.com/mourya-dasgupta/evalgate/issues/10)

**Labels:** `enhancement`, `integration`, `roadmap:later`

**Context.** Coding agents increasingly edit prompts. They should check the golden set
before proposing a change.

**Acceptance criteria**
- [ ] `evalgate mcp` starts a stdio MCP server exposing `validate`, `run`, `gate` and `report` tools.
- [ ] Tool results return the JSON report (verdict, failed rules, flips) in a compact form.
- [ ] Record/live modes are disabled unless explicitly enabled by flag (no surprise API spend).
- [ ] Documented with an example client configuration.
