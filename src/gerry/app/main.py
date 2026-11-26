"""FastAPI application entrypoint.

Thin HTTP layer: routes validate input, call into core/store, and render.
Business logic belongs in gerry.core (pure) or gerry.store (I/O).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from gerry import __version__
from gerry.settings import get_settings

logger = logging.getLogger(__name__)

app = FastAPI(title="Gerry", version=__version__)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe. Must stay dependency-free so it works during incidents."""
    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "environment": settings.environment,
        "git_sha": settings.git_sha,
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    settings = get_settings()
    return f"""<!doctype html>
<html><head><title>Gerry</title>
<style>
 body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 42rem;
        margin: 4rem auto; padding: 0 1rem; line-height: 1.6; }}
 code {{ background: #f4f4f5; padding: .15rem .35rem; border-radius: 3px; }}
 .muted {{ color: #71717a; font-size: .9rem; }}
</style></head>
<body>
  <h1>Gerry</h1>
  <p>AI-assisted photo culling and delivery pipeline.</p>
  <p class="muted">v{__version__} &middot; {settings.environment} &middot;
     build <code>{settings.git_sha}</code></p>
</body></html>"""
