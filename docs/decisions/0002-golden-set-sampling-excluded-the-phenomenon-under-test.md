# ADR 0002 — Golden-set sampling excluded the phenomenon under test

- **Status:** accepted
- **Date:** 2026-11-25
- **Supersedes:** ADR 0001

## Context

ADR 0001 concluded that low keep-precision (0.54) was caused by the model
scoring frames in isolation, unable to replicate the comparative judgement a
photographer makes inside a burst. It proposed best-of-group selection:
within each near-duplicate group, promote the strongest frame and demote the
rest.

That was implemented (`gerry.core.selection`, 20 unit tests) and measured
against the same 349-frame golden set before being wired into the pipeline.

## What the measurement showed

Applying group selection to existing v2 predictions, at three phash
thresholds:

| phash distance | frames in groups | precision | recall |
|---|---|---|---|
| none (baseline) | — | **0.540** | **0.683** |
| 8 | 51 | 0.493 | 0.532 |
| 12 | 72 | 0.447 | 0.424 |
| 16 | 130 | 0.431 | 0.338 |

Every configuration made both metrics **worse**. The intervention intended
to fix precision reduced it.

## Root cause

The golden set was built by `tools/build_golden_set.py`, whose
`select_frames()` takes frames **evenly spaced across a shoot**:

```python
step = len(files) / limit
return [files[int(i * step)] for i in range(limit)]
```

This was written to spread coverage across a session and avoid clustering on
test shots at the head of a shoot. Its unintended consequence is decisive:
**sampling every ~10th frame guarantees that consecutive burst frames are
never both present.**

Three conclusions follow:

1. **The golden set cannot test the burst hypothesis.** The phenomenon was
   removed by the sampling strategy before labeling began.
2. **The "duplicate groups" phash finds in this set are not bursts.** They are
   coincidentally similar frames from different moments. Demoting them
   discards genuine keeps, which is exactly what the metrics show.
3. **Comparative culling cannot explain the precision gap.** The labeler saw
   non-adjacent frames, so the human judgements were themselves largely
   absolute, not comparative.

ADR 0001 was a plausible hypothesis argued from a real pattern (recall 1.00
with precision 0.43 on the BMX shoot), but it was adopted before being
tested, and the test refutes it.

## Decision

1. **Revert group selection from the scoring path.** Keep the module and its
   tests — the logic is correct and will be needed once bursts are actually
   represented — but it must not run until there is evidence it helps.
2. **Treat the golden set's sampling as a known limitation**, documented
   alongside the data.
3. **Do not accept an architectural conclusion without measuring it.** ADR
   0001 reasoned from aggregate patterns to a cause. The measurement was
   cheap (zero model spend — it reuses stored predictions) and should have
   preceded the decision.

## Consequences

- The cause of the 0.54 precision gap is **still unknown**. Remaining
  candidates: the rubric does not capture the photographer's actual
  standards; the standards are partly subjective and not inferable from a
  single frame; or the labels encode shoot-level context ("I have enough
  from this angle") unavailable to a per-frame scorer.
- Diagnosing it requires **inspecting actual disagreements**, not more
  aggregate metrics.
- Testing the burst hypothesis properly requires a **second golden set built
  from consecutive frames** within bursts. That is a different sampling
  strategy, not a bigger sample.

## Note on method

Both the wrong conclusion and its correction cost ~$0 to evaluate, because
per-frame predictions are persisted (`--predictions-out`) and the analysis
reruns offline. Storing predictions rather than only aggregate metrics is
what made the error cheap to find.
