# Gerry

An AI-assisted photo culling and delivery pipeline. Upload a shoot, get a
ranked cull with reasons, review and override, deliver a private client gallery.

> **What's with the name?** Named after
> [Gerry Cliff](https://ameeras-fanfiction-collection.fandom.com/wiki/Gerry_Cliff)
> from Blue Lights, for no specific reason.

## Status

**Live:** https://gerry-cull.fly.dev — [`/healthz`](https://gerry-cull.fly.dev/healthz)

End-to-end working in production: upload → S3 → pre-filter → vision scoring →
threshold → review UI → client gallery, with every model call costed.

| | measured |
|---|---|
| Cost per 100 frames | **$0.83** |
| Ranking quality (AUC) | **0.657** on a 349-frame golden set |
| Precision at the shipping threshold (83) | **0.842** |
| Recall at that threshold | 0.115 |

**What it is honestly good at:** surfacing the strongest frames for review.
At threshold 83 it finds ~19 frames at 84% precision from 349 — a useful
first pass, not a replacement for culling. See
[ADR 0003](docs/decisions/0003-score-and-threshold-instead-of-asking-for-a-verdict.md).

### Operational notes

- The Fly Postgres machine auto-stops when idle. If the app 500s, check
  `fly status --app gerry-db` and `fly machine start <id>`.
- Free-tier organisations are limited to 3 machines; the app runs a single
  instance (`fly scale count 1`) to leave room for the database.

## How it works

```
upload ──▶ S3 ──▶ queue ──▶ worker
                              │
                              ├─ 1. pre-filter  (deterministic, $0)
                              │     perceptual-hash duplicate groups
                              │     blur + exposure checks
                              │
                              ├─ 2. vision scoring  (model, metered)
                              │     keep / maybe / reject + reason
                              │     keywords + alt text
                              │
                              └─ 3. review UI ──▶ approve/override
                                                       │
                                                       └─▶ signed gallery link
```

Deterministic work happens first so the model only sees frames worth paying for.
Overrides in the review UI become candidate additions to the eval set.

## Evaluation

A hand-labeled golden set of real frames (keep/maybe/reject, including burst
duplicates, deliberate motion blur, and backlit portraits) gates every merge.

CI fails if **keep-precision** drops below threshold or **cost per 100 images**
rises more than 20% against `main`.

Latest eval results: _pending_

## Development

> **Note:** this project uses `uv`'s default in-project `.venv` rather than the
> `~/virtualenvs/<repo>` convention used elsewhere. `uv run` activates it
> automatically, and the Dockerfile and CI both assume it — so never `source`
> anything. If you have another venv active, `deactivate` first.

```bash
uv sync --extra dev
uv run pre-commit install

uv run pytest                 # unit + integration
uv run ruff check . && uv run mypy
uv run uvicorn gerry.app.main:app --reload
```

Local Postgres:

```bash
colima start                  # if not already running
docker run --rm -d --name gerry-pg \
  -e POSTGRES_PASSWORD=test -e POSTGRES_DB=gerry \
  -p 55432:5432 postgres:16-alpine
```

### Building the golden set

```bash
# 1. convert RAW frames from real shoots to JPEGs
python tools/build_golden_set.py \
  --shoot /Volumes/scrappy/photos/2026/2026_02_15_dunstan_head_shots \
  --per-shoot 75

# 2. label them in the browser (recommended) -> http://localhost:8000
python tools/label_web.py      # K=keep  M=maybe  R=reject  U=undo

# ...or in the terminal, if you prefer
python tools/label.py          # k/m/r, q to quit
```

Both write the same `labels.csv` and are resumable -- stop any time.

Labels (`data/golden/labels.csv`) are committed; **images are not**.

## Configuration

Non-secret config in `config.yaml`; secrets via environment (`.env` locally,
Fly secrets in production). See `.env.example`.

## Decision records

See [`docs/decisions/`](docs/decisions/).

## Contributing

Commit attribution conventions and the quality gate: [`CONTRIBUTING.md`](CONTRIBUTING.md).
