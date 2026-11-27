# ADR 0001 — Per-frame scoring cannot replicate comparative burst culling

- **Status:** SUPERSEDED by ADR 0002 — the central hypothesis was not supported
- **Date:** 2026-11-25
- **Context:** v1/v2 prompt evaluation against a 349-frame golden set

> **Retraction (same day):** the decision below was reversed within hours of
> being written. Implementing best-of-group selection and measuring it made
> metrics *worse*, and investigation showed the golden set could not test the
> hypothesis at all. Kept in the repo rather than deleted, because the
> reasoning error is instructive. See ADR 0002.

## Context

The initial pipeline asked a vision model to score each frame in isolation
against an absolute rubric, returning keep/maybe/reject. Two prompt versions
were evaluated against a hand-labeled golden set of 349 real frames across
six shoots.

## What the evaluation showed

Identical frames, two prompts:

| metric | cull_v1 | cull_v2 |
|---|---|---|
| keep-precision | 0.567 | 0.540 |
| keep-recall | 0.489 | 0.683 |
| agreement | 0.607 | 0.616 |
| false keeps | 52 | 81 |

Neither came close to the 0.80 precision floor. More informative was the
breakdown by shoot type (v2):

| shoot | type | precision | recall | false keeps |
|---|---|---|---|---|
| dunstan headshots | studio portrait | **0.79** | 0.88 | 12 |
| linkedin headshots | studio portrait | 0.62 | 0.91 | 6 |
| alameda bmx | burst action | 0.43 | **1.00** | 26 |
| ride for a reason | burst action | 0.40 | 0.38 | 12 |
| back roads bash | event candid | 0.35 | 0.40 | 11 |
| les misérables | stage | 0.30 | 0.29 | 14 |

Three observations:

1. **Performance is bimodal by shoot type.** Studio portraiture nearly meets
   the floor (0.79). Burst-heavy action collapses (0.43).
2. **On the BMX shoot the model kept effectively every frame** (recall 1.00)
   while the photographer kept 32%.
3. **75 of 81 false keeps were labeled `reject`**, not `maybe` — these were
   not marginal calls.

## Decision

**The model was being asked the wrong question.**

A photographer culling a burst does not judge frames absolutely. They judge
them *comparatively*: of these eleven near-identical frames, which one has the
best expression, the sharpest eyes, the best moment? The other ten get
rejected not because they are bad, but because a better one exists.

A model scoring frames in isolation has no access to that context. It cannot
know that frame 47 is redundant with frame 46. Asking it to replicate a
comparative judgment with per-frame information is not a prompt-engineering
problem — it is an information problem, and no rubric wording can solve it.

Corroborating evidence: v1 and v2 produced identical verdicts on **78%** of
frames despite substantially different instructions, including an explicitly
reversed stance on conservatism. The prompt was not the binding constraint.

Therefore the pipeline splits the judgment in two:

1. **Per-frame technical assessment** (model): is this frame deliverable at
   all — focus, eyes, exposure, composition? This is what per-frame
   information actually supports, and where the model already performs well.
2. **Best-of-group selection** (pipeline): within each near-duplicate group
   identified by the deterministic pre-filter, rank and promote the strongest
   frame; demote the rest to `maybe` rather than `keep`.

## Consequences

**Positive**
- Addresses the measured cause rather than tuning around it.
- Uses the perceptual-hash grouping the pre-filter already computes, at no
  model cost.
- Matches the review UI the spec already called for ("suggested picks by
  duplicate group").
- Expected to cut false keeps substantially on burst-heavy shoots, which is
  where nearly all of them occur.

**Negative**
- Group quality now matters: too loose a hash threshold merges distinct
  frames, too tight leaves bursts ungrouped. This becomes a tunable with its
  own failure modes.
- A single global precision floor remains questionable given bimodal
  performance by shoot type. Deferred to a later ADR.

**Costs incurred reaching this decision:** ~$7.40 of model spend across five
eval runs. Cheap for the finding.

## Alternatives considered

- **Continue prompt iteration.** Rejected: the 78% v1/v2 agreement indicates
  diminishing returns, and two opposed framings produced similar errors.
- **Lower the precision floor to match observed performance.** Rejected as a
  primary fix — it would make the gate pass without making the product
  better. Revisiting the threshold is still warranted, but on evidence and
  after the architecture is right.
- **Send whole bursts to the model in one request.** Deferred: materially more
  expensive per call, more complex to validate, and the deterministic grouping
  achieves most of the benefit at zero model cost.
