## EvalGate: ✅ PASS

Run `2026-11-03T07-04-01-208821Z` vs baseline `2026-11-03T07-03-59-670128Z` · mode `replay`

| Suite | Cases | Pass rate | Δ vs baseline | Score | Flips | Verdict |
|---|---:|---:|---:|---:|---:|---|
| triage | 66 | 89.4% | ±0.0 pp | 0.954 | 0 | ✅ PASS |

**triage** — gate rules

- ✅ `min_pass_rate`: pass rate 89.4% meets the floor of 80.0%
- ✅ `max_regression`: pass rate moved +0.0 pp vs baseline (allowed drop: 5 pp)
- ✅ `max_new_failures`: 0 case(s) flipped from pass to fail (allowed: 3)
- ✅ `critical_tags`: all cases tagged ['critical'] pass

<details>
<summary>Pass rate by tag — triage</summary>

| Tag | Cases | Pass rate | Δ vs baseline |
|---|---:|---:|---:|
| `angry-low` | 6 | 100.0% | ±0.0 pp |
| `b2b` | 3 | 100.0% | ±0.0 pp |
| `bengali` | 9 | 100.0% | ±0.0 pp |
| `critical` | 11 | 100.0% | ±0.0 pp |
| `hinglish` | 16 | 87.5% | ±0.0 pp |
| `injection` | 8 | 87.5% | ±0.0 pp |
| `multi-issue` | 7 | 85.7% | ±0.0 pp |
| `polite-urgent` | 5 | 100.0% | ±0.0 pp |
| `sarcasm` | 6 | 50.0% | ±0.0 pp |
| `security` | 3 | 100.0% | ±0.0 pp |

</details>

**Verdict: ✅ PASS** — all suites passed the gate.
