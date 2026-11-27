❌ **Eval gate failed**

`n = 215` frames

| metric | this run | baseline | change |
|---|---|---|---|
| keep-precision | 0.717 | — | — |
| keep-recall | 0.409 | — | — |
| agreement | 0.609 | — | — |
| cost / 100 imgs | $0.7490 | — | — |
| p95 latency (ms) | 3627 | — | — |

<sub>keep: 38 correct, **15 false keeps**, 55 missed</sub>

**Blocking issues:**
- keep-precision 0.717 is below the floor of 0.800
