## EvalGate: ❌ FAIL

Run `2026-11-03T06-00-00-000000Z` vs baseline `2026-11-01T00-00-00-000000Z` · mode `replay`

| Suite | Cases | Pass rate | Δ vs baseline | Score | Flips | Verdict |
|---|---:|---:|---:|---:|---:|---|
| sentiment | 5 | 80.0% | -20.0 pp | 0.867 | 1 | ❌ FAIL |
| echo | 1 | 100.0% | ±0.0 pp | 1.000 | 0 | ✅ PASS |

**sentiment** — gate rules

- ✅ `min_pass_rate`: pass rate 80.0% meets the floor of 60.0%
- ❌ `max_regression`: pass rate moved -20.0 pp vs baseline (allowed drop: 5 pp)
- ✅ `max_new_failures`: 1 case(s) flipped from pass to fail (allowed: 1)
- ✅ `critical_tags`: all cases tagged ['critical'] pass

<details>
<summary><b>1 flipped case(s) in sentiment</b> (passed in the baseline, failing now)</summary>

#### `s5` · tags: tricky

**Input**

```json
{
  "text": "Not great, honestly awful"
}
```

**Expected**

```json
{
  "label": "negative"
}
```

**Actual**

```
{
  "label": "positive"
}
```

**Why it fails:** `label_match:label: expected 'negative', predicted 'positive'`

</details>

<details>
<summary>Pass rate by tag — sentiment</summary>

| Tag | Cases | Pass rate | Δ vs baseline |
|---|---:|---:|---:|
| `critical` | 1 | 100.0% | ±0.0 pp |
| `tricky` | 1 | 0.0% | -100.0 pp |

</details>

**echo** — gate rules

- ⚠️ no gate rules configured; this suite always passes

**Verdict: ❌ FAIL** — 1 of 2 suite(s) failed the gate: sentiment.
