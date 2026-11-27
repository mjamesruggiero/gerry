# ADR 0003 — Ask the model to rank, choose the threshold ourselves

- **Status:** accepted
- **Date:** 2026-11-25
- **Related:** ADR 0001 (superseded), ADR 0002

## Context

Three prompt revisions were evaluated against the same 349-frame golden set:

| prompt | precision | recall | F1 | agreement |
|---|---|---|---|---|
| cull_v1 | 0.567 | 0.489 | 0.525 | 0.607 |
| cull_v2 | 0.540 | 0.683 | 0.603 | 0.616 |
| cull_v3 | 0.485 | 0.813 | **0.608** | 0.562 |

Each revision moved the operating point along a precision/recall tradeoff.
**F1 was flat between v2 and v3** (0.603 → 0.608) and agreement fell. The
prompts were not improving the model's ability to tell good frames from bad;
they were only moving where it drew the line.

Continuing to tune prompts would have kept rediscovering the same frontier at
~$2.90 per measurement.

## Decision

**Ask the model for a 0-100 deliverability score, and choose the keep/reject
threshold ourselves against the golden set.**

This separates two things the previous design conflated:

1. **The model's judgement** — how good is this frame? (ranking)
2. **The business decision** — how conservative should we be? (threshold)

The threshold becomes an explicit, tunable config value, swept offline at
zero model cost, rather than an emergent property of prompt wording.

## What the scores revealed

`cull_v4` emits a quality score. Sweeping the threshold (free, on stored
predictions):

| threshold | keeps | precision | recall | F1 |
|---|---|---|---|---|
| 40 | 248 | 0.460 | 0.820 | 0.589 |
| **45** | 197 | 0.533 | 0.755 | **0.625** |
| 50 | 126 | 0.556 | 0.504 | 0.528 |
| 85 | 19 | **0.842** | 0.115 | 0.203 |
| 90 | 5 | 1.000 | 0.036 | 0.069 |

**Discriminative power, measured as AUC** (probability a random kept frame
outscores a random rejected one):

| shoot | type | n | AUC |
|---|---|---|---|
| alameda bmx | burst action | 63 | **0.875** |
| back roads bash | event candid | 53 | 0.726 |
| dunstan headshots | studio portrait | 75 | 0.715 |
| ride for a reason | action | 75 | 0.686 |
| les misérables | stage | 65 | 0.563 |
| linkedin headshots | studio portrait | 18 | **0.461** |
| **overall** | | 349 | **0.657** |

Three conclusions:

1. **The ranking signal is real but uneven.** Overall AUC 0.657 is well above
   chance and far below strong.
2. **A single global threshold destroys per-shoot signal.** The BMX shoot has
   the model's *best* ranking (AUC 0.875) and had its *worst* precision
   (0.43) under a fixed verdict. The information was there; the decision rule
   discarded it.
3. **On some shoot types the model does not share the photographer's
   judgement at all** — stage work (0.563) and corporate headshots (0.461,
   below chance). No threshold rescues a ranking that isn't there.

A fourth, practical note: despite being instructed to use the full range, the
model **clusters scores** — 70 frames scored exactly 48, 57 at 32, 51 at 42.
This quantization limits threshold resolution; thresholds between adjacent
clusters are equivalent.

## Consequences

**Positive**
- The operating point is now a measured decision with a documented tradeoff,
  not an accident of wording.
- Re-tuning costs $0 — the sweep runs on stored predictions.
- Per-shoot-type thresholds become possible, which the AUC spread shows is
  worth doing.
- Honest product framing is now available: the system is good at *surfacing
  strong candidates*, not at *replicating a complete cull*.

**Negative**
- At the 0.80 precision target the achievable recall is 0.115 — only 19 of
  139 real keeps. As an autonomous culler that is not useful.
- Score clustering limits resolution.
- Per-shoot thresholds need per-shoot labels, which raises the labeling cost
  of onboarding a new type of work.

## Product implication

The honest positioning for v1 is **"surface the best frames for review"**,
not "cull the shoot for you". At threshold 85 the system finds 19 frames at
84% precision — a genuinely useful first pass through a 500-frame shoot,
with the photographer reviewing the rest.

Claiming automated culling would be unsupported by this data, and the review
UI already assumes a human decides.

## Cost of reaching this decision

~$13.30 of model spend across seven eval runs. The threshold sweep and AUC
analysis that produced the key insight cost **$0** — they ran on stored
predictions, which is the argument for persisting per-frame output rather
than only aggregate metrics.
