# Roadmap

v0.1.0 ships the core loop: golden sets → record/replay → score → compare → gate → report,
as a CLI and a GitHub Action. Next steps, grouped by horizon. Each item says why it matters.
Detailed issue drafts are in [issues-to-create.md](issues-to-create.md).

## Now

- **Sampling + statistical significance for noisy evals.** Run each case N times (in live
  mode or with multiple recordings) and gate on a confidence interval instead of a single
  pass rate. *Why it matters:* a 2 pp drop on 60 cases is often noise; teams should not chase
  it, and should not miss a real one.
- **Cost and latency tracking per run.** Record token usage and latency per case (already
  captured in cassettes) and add `max_cost_increase` / `max_p95_latency` gate rules. *Why it
  matters:* the most common silent regression after a prompt change is a 40% longer
  prompt, not a wrong answer.
- **PR-comment bot via the GitHub API.** A first-class `comment: true` input on the action
  that posts and updates one sticky comment (the example workflow does this with
  `github-script` today). *Why it matters:* reviewers read PR comments, not job summaries.
- **`evalgate cassette prune`.** Remove entries no current config can produce. *Why it
  matters:* record mode upserts by design, so stale recordings slowly bloat repositories.

## Next

- **Dataset versioning.** Hash and version golden sets; store the golden-set version in runs
  and compare only the shared cases when the set changes. *Why it matters:* today a golden-set
  edit makes the delta compare different case sets (EvalGate warns, but cannot correct it).
- **RAG-specific scorers (faithfulness, context recall).** Judge- and overlap-based scorers
  that take retrieved context from a `python` provider's response. *Why it matters:* most
  production LLM features are retrieval pipelines, and their failures are grounding failures.
- **Multi-turn and agent trajectory evals.** Golden cases with conversations and expected
  tool calls; scorers over the trajectory, not just the final text. *Why it matters:* agents
  regress in the middle of a conversation (wrong tool, loop), not only at the end.
- **pytest plugin mode.** `pytest --evalgate` collects suites as tests, so teams can adopt
  EvalGate inside an existing test run and IDE. *Why it matters:* lower adoption cost for teams
  that already gate on pytest.
- **Judge calibration report.** Compare `llm_judge` verdicts with a small human-labelled set
  and report agreement. *Why it matters:* a judge you have not measured is just another
  untested model.

## Later

- **Trend dashboard.** A static site generated from committed baselines and run JSON,
  showing pass rate per suite and tag over time. *Why it matters:* quality should be visible
  to PMs and support leads, not only in CI logs. Static, so still no database.
- **MCP server so agents can run evals.** Expose `validate`, `run`, `gate` and `report` as MCP
  tools. *Why it matters:* coding agents that edit prompts should check their own changes
  against the golden set before opening a PR.
- **Gate my other portfolio projects with EvalGate.** Add suites for ClassKhata, LedgerLift and
  HuntDeck and run the action on their PRs. *Why it matters:* dogfooding on different feature
  shapes (extraction, classification, generation) is the fastest way to find gaps.
- **More providers** (Gemini, Bedrock, Azure OpenAI with AAD auth). *Why it matters:* customers
  standardise on whatever their cloud contract includes.

## Non-goals (v1)

No hosted dashboard, no database, no dataset-labelling UI, no tracing/observability, no
fine-tuning. EvalGate stays a small, file-based gate that composes with those tools.
