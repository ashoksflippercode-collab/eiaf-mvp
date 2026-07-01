"""EIAF entry point (PRD §3.0, §5).

A FastAPI application exposing the API surface for the Tier-1 pipeline. This is
where the shared envelope is minted (the single point that generates the
`request_id`) before the request flows through the layers.

TRUST BOUNDARY: `user_id` / `role` are taken from the request as set by a trusted
upstream component (API gateway / authenticated front-end) — see the Service
Layer docstring. In production these MUST originate from a validated session, not
from an untrusted client.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import __version__
from backend.envelope import Envelope
from backend.pipeline import build_tier1_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Enterprise Information Access Framework (EIAF)", version=__version__)

# Allow local-dev front-ends (e.g. VS Code Live Server on :5500) to call the API
# cross-origin. Restrict to localhost; production should set explicit origins.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)

pipeline = build_tier1_pipeline()


class AskRequest(BaseModel):
    text: str = Field(..., description="The user's natural-language question.")
    # Identity injected by the trusted upstream. Defaults model the single MVP Admin.
    user_id: str = Field(default="admin-user")
    role: str = Field(default="admin")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post("/ask")
def ask(request: AskRequest) -> dict:
    """Run a question through the full pipeline and return the shared envelope.

    The HTTP status is always 200; success vs. failure is conveyed inside the
    envelope (`status` + structured `error`), honoring the §6.4 error contract.
    """
    envelope = Envelope.create(
        user_id=request.user_id,
        role=request.role,
        payload={"text": request.text},
    )
    result = pipeline.run(envelope)
    return result.model_dump()


# Serve the minimal front-end (index.html, voice.js). Mounted last so API routes
# above take precedence.
if _FRONTEND_DIR.is_dir():
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(_FRONTEND_DIR / "index.html")

    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR)), name="frontend")
