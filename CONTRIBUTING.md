# Contributing

## Commit attribution

This repo tracks which commits were authored with agent assistance, so the
agent-authored share can be measured against defect and revert rates.

**Agent-authored or agent-assisted commits carry a trailer:**

```
Co-Authored-By: pi <pi@earendil.works>
```

**Human-only commits carry no trailer.** That asymmetry is the point -- if
everything is tagged, the ratio means nothing.

Report with:

```bash
python scripts/attribution_report.py
```

## Quality gate

Every PR must pass:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

Install the hooks once so this runs locally:

```bash
uv run pre-commit install
```

## Test layers

| Layer | Location | Network | Runs |
|---|---|---|---|
| unit | `tests/unit/` | none (model mocked) | every PR |
| integration | `tests/integration/` | local Postgres | every PR |
| eval | `evals/` | **real model API, costs money** | prompt/model PRs + nightly |

Eval tests are marked `@pytest.mark.eval` and excluded from the default run.
