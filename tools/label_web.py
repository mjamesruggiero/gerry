#!/usr/bin/env python3
"""Browser-based labeling for the golden set.

Quick Look turned out to be unreliable for rapid labeling (window focus,
no keyboard capture). A local web page is faster and more predictable: the
image fills the window, keystrokes are captured directly, and progress is
visible.

    python tools/label_web.py          # then open http://localhost:8000

Keys:  K = keep   M = maybe   R = reject   U = undo   (arrow keys navigate)

Writes the same labels.csv format as tools/label.py, so the two are
interchangeable.
"""

from __future__ import annotations

import argparse
import csv
import logging
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("label_web")

FIELDNAMES = ["filename", "label", "labeled_at"]
VALID = {"keep", "maybe", "reject"}


def load_labels(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(newline="") as fh:
        return {r["filename"]: r["label"] for r in csv.DictReader(fh)}


def write_labels(path: Path, labels: dict[str, str]) -> None:
    """Rewrite the whole file so undo/relabel works cleanly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        for name, label in labels.items():
            writer.writerow({"filename": name, "label": label, "labeled_at": now})


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Gerry · label golden set</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; background:#09090b; color:#e4e4e7; height:100vh;
         font-family:-apple-system,system-ui,sans-serif;
         display:flex; flex-direction:column; }
  header { padding:.6rem 1rem; display:flex; gap:1.5rem; align-items:center;
           border-bottom:1px solid #27272a; font-size:.85rem; }
  .bar { flex:1; height:6px; background:#27272a; border-radius:3px; overflow:hidden; }
  .bar > div { height:100%; background:#22c55e; width:0%; transition:width .2s; }
  main { flex:1; display:flex; align-items:center; justify-content:center;
         overflow:hidden; padding:.5rem; }
  img { max-width:100%; max-height:100%; object-fit:contain; border-radius:4px; }
  footer { padding:.6rem 1rem; border-top:1px solid #27272a; display:flex; gap:1rem;
           align-items:center; font-size:.85rem; }
  kbd { background:#27272a; border:1px solid #3f3f46; border-radius:4px;
        padding:.1rem .4rem; font-family:ui-monospace,monospace; }
  .name { color:#71717a; font-size:.75rem; }
  .counts span { margin-right:.9rem; }
  .keep{color:#22c55e} .maybe{color:#eab308} .reject{color:#ef4444}
  .done { text-align:center; padding:3rem; }
</style></head>
<body>
  <header>
    <strong>Gerry</strong>
    <div class="bar"><div id="bar"></div></div>
    <span id="progress">—</span>
  </header>
  <main><img id="img" alt=""></main>
  <footer>
    <span><kbd>K</kbd> <span class="keep">keep</span></span>
    <span><kbd>M</kbd> <span class="maybe">maybe</span></span>
    <span><kbd>R</kbd> <span class="reject">reject</span></span>
    <span><kbd>U</kbd> undo</span>
    <span class="counts" id="counts"></span>
    <span class="name" id="name"></span>
  </footer>
<script>
let state = null;

async function refresh() {
  const r = await fetch('/api/next');
  state = await r.json();
  if (state.done) {
    document.querySelector('main').innerHTML =
      '<div class="done"><h2>All ' + state.total + ' frames labeled</h2>' +
      '<p>Labels written to data/golden/labels.csv</p></div>';
    document.getElementById('img')?.remove();
  } else {
    document.getElementById('img').src = '/images/' + encodeURIComponent(state.filename);
    document.getElementById('name').textContent = state.filename;
  }
  const pct = state.total ? (100 * state.labeled / state.total) : 0;
  document.getElementById('bar').style.width = pct + '%';
  document.getElementById('progress').textContent =
    state.labeled + ' / ' + state.total;
  document.getElementById('counts').innerHTML =
    '<span class="keep">keep ' + state.counts.keep + '</span>' +
    '<span class="maybe">maybe ' + state.counts.maybe + '</span>' +
    '<span class="reject">reject ' + state.counts.reject + '</span>';
}

async function send(label) {
  if (!state || state.done) return;
  await fetch('/api/label', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({filename: state.filename, label: label}),
  });
  refresh();
}

async function undo() {
  await fetch('/api/undo', {method: 'POST'});
  refresh();
}

document.addEventListener('keydown', e => {
  const k = e.key.toLowerCase();
  if (k === 'k') send('keep');
  else if (k === 'm') send('maybe');
  else if (k === 'r') send('reject');
  else if (k === 'u') undo();
});
refresh();
</script>
</body></html>"""


def build_app(images_dir: Path, labels_path: Path) -> FastAPI:
    app = FastAPI(title="gerry-labeler")
    app.mount("/images", StaticFiles(directory=str(images_dir)), name="images")
    order: list[str] = sorted(p.name for p in images_dir.glob("*.jpg"))
    history: list[str] = []

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return PAGE

    @app.get("/api/next")
    def next_frame() -> JSONResponse:
        labels = load_labels(labels_path)
        counts = {v: sum(1 for x in labels.values() if x == v) for v in VALID}
        remaining = [n for n in order if n not in labels]
        return JSONResponse(
            {
                "filename": remaining[0] if remaining else None,
                "done": not remaining,
                "labeled": len(labels),
                "total": len(order),
                "counts": counts,
            }
        )

    @app.post("/api/label")
    async def set_label(payload: dict[str, str]) -> JSONResponse:
        filename, label = payload.get("filename", ""), payload.get("label", "")
        if label not in VALID:
            raise HTTPException(400, f"invalid label: {label!r}")
        labels = load_labels(labels_path)
        labels[filename] = label
        write_labels(labels_path, labels)
        history.append(filename)
        logger.info("%s -> %s (%d labeled)", filename, label, len(labels))
        return JSONResponse({"ok": True})

    @app.post("/api/undo")
    def undo() -> JSONResponse:
        if not history:
            return JSONResponse({"ok": False, "reason": "nothing to undo"})
        last = history.pop()
        labels = load_labels(labels_path)
        labels.pop(last, None)
        write_labels(labels_path, labels)
        logger.info("undid %s", last)
        return JSONResponse({"ok": True, "undid": last})

    @app.get("/favicon.ico")
    def favicon() -> FileResponse:
        raise HTTPException(404)

    return app


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--images", type=Path, default=Path("data/golden/images"))
    ap.add_argument("--labels", type=Path, default=Path("data/golden/labels.csv"))
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not args.images.is_dir():
        logger.error("no such directory: %s", args.images)
        return 2

    n = len(list(args.images.glob("*.jpg")))
    logger.info("serving %d images -> http://localhost:%d", n, args.port)
    uvicorn.run(
        build_app(args.images, args.labels), host="127.0.0.1", port=args.port, log_level="warning"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
