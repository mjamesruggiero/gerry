# ADR 0004 — Gate thresholds set from measurement, not aspiration

- **Status:** accepted
- **Date:** 2026-11-25
- **Related:** ADR 0003

## Context

The initial gate used `min_keep_precision = 0.80`, written into `config.yaml`
before any measurement existed. After seven eval runs it was clear that:

- No prompt version reached 0.80 precision on raw verdicts (best: 0.567).
- With threshold selection, 0.80 precision is reachable only at **11.5%
  recall** (19 keeps of 139).
- v1's 0.717 on the original 215-frame set had a 95% CI of [0.584, 0.820] —
  the floor sat *inside* the confidence interval, so the gate's verdict was
  not statistically meaningful at that sample size.

A gate nothing can pass is as useless as one nothing can fail: it gets
disabled the first time it is inconvenient.

## Decision

**Gate primarily on AUC, secondarily on precision at the shipping threshold.**

| threshold | value | rationale |
|---|---|---|
| `min_auc` | **0.60** | Measured baseline 0.657. 0.5 is chance. Primary signal. |
| `max_auc_drop` | **0.05** | Relative guard against a slow slide vs baseline. |
| `min_keep_precision` | **0.75** | Measured 0.842 at the shipping threshold; leaves headroom for noise. |
| `max_cost_increase_pct` | 20 | Unchanged. |
| `keep_threshold` | **83** | From the sweep: precision 0.842, recall 0.115. |

### Why AUC is primary

It is **threshold-independent**. It asks whether the model can rank frames at
all, separately from where we choose to cut. Precision at a fixed threshold
moves when the score distribution shifts even if ranking is unchanged — and
the model demonstrably clusters its scores (70 frames at exactly 48), so
distribution shifts are likely.

Concretely: a prompt change that shifts every score up by 10 points would
tank precision-at-83 while changing the model's actual judgement not at all.
AUC is invariant to that, and a unit test pins the property.

### Why precision is kept as a secondary check

AUC can stay healthy while the *delivered* product degrades, if the chosen
threshold drifts out of calibration. Precision at the shipping threshold is
what a client would actually experience.

## Consequences

**Positive**
- The gate is live and meaningful today: it passes at threshold 83 (the
  shipping configuration) and fails at 43, verified against stored
  predictions.
- Thresholds are traceable to a measurement rather than to an opinion.
- Re-tuning costs $0 — the sweep runs offline.

**Negative**
- 0.75 precision is a *lower* bar than originally written down. This is an
  honest reflection of measured capability, not a loosening to make CI green;
  the shipped operating point measures 0.842 against it.
- Shipping recall of 11.5% means the product surfaces strong candidates
  rather than performing the cull. ADR 0003 records that positioning.
- The floors should **ratchet upward** as prompts improve. A threshold set
  from measurement must not become a permanent ceiling.

## Alternatives considered

- **Keep 0.80 and ship nothing until it is met.** Rejected: three prompt
  revisions showed a flat F1 frontier, so there was no evidence the target
  was reachable by tuning.
- **Gate on F1 at the best operating point.** Rejected as primary: F1 blends
  two quantities with very different business costs here. A false keep
  reaches a client; a false reject does not.
- **Per-shoot-type thresholds.** Deferred, but strongly indicated: AUC ranges
  from 0.875 (BMX) to 0.461 (LinkedIn headshots). A single global threshold
  is leaving signal on the table. Needs per-type labels to calibrate.
