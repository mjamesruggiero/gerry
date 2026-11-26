# Gerry

An AI-assisted photo culling and delivery pipeline. Upload a shoot, get a
ranked cull with reasons, review and override, deliver a private client gallery.

> **What's with the name?** Named after
> [Gerry Cliff](https://ameeras-fanfiction-collection.fandom.com/wiki/Gerry_Cliff)
> from Blue Lights, for no specific reason.

## Status

Week 1 — scaffolding. Not yet deployed.

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
python tools/build_golden_set.py \
  --shoot /Volumes/scrappy/photos/2026/2026_02_15_dunstan_head_shots \
  --per-shoot 75
python tools/label.py          # k=keep  m=maybe  r=reject  q=quit
```

Labels (`data/golden/labels.csv`) are committed; **images are not**.

## Configuration

Non-secret config in `config.yaml`; secrets via environment (`.env` locally,
Fly secrets in production). See `.env.example`.

## Decision records

See [`docs/decisions/`](docs/decisions/).

## Contributing

Commit attribution conventions and the quality gate: [`CONTRIBUTING.md`](CONTRIBUTING.md).
