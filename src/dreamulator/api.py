"""FastAPI application for dreamulator."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from dreamulator.api_routes.worlds import router as worlds_router

app = FastAPI(
    title="Dreamulator API",
    description="Fantasy world building and simulation tool",
    version="0.1.0",
)

# CORS for frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(worlds_router)


@app.get("/api/health")
def health_check() -> dict[str, object]:
    """Health check endpoint."""
    return {"ok": True, "service": "dreamulator"}


# ---------------------------------------------------------------------------
# Frontend static file serving
# ---------------------------------------------------------------------------

def _find_frontend_dist() -> Path | None:
    """Walk up from project root to find frontend/dist/."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            dist = current / "frontend" / "dist"
            if dist.exists():
                return dist
            return None
        current = current.parent
    return None


_frontend_dist = _find_frontend_dist()


@app.get("/", response_model=None, include_in_schema=False)
def serve_index() -> Response:
    """Serve the frontend SPA entry point."""
    if _frontend_dist is not None:
        index_file = _frontend_dist / "index.html"
        if index_file.exists():
            return HTMLResponse(index_file.read_text(encoding="utf-8"))
    return PlainTextResponse(
        "Dreamulator API is running.\n"
        "To use the web UI, build the frontend first:\n"
        "  cd frontend && npm run build\n"
        "Then restart the server.",
        status_code=200,
    )


@app.get("/{full_path:path}", response_model=None, include_in_schema=False)
def serve_spa(request: Request) -> Response:
    """Catch-all: serve static assets or fall back to index.html for SPA routing."""
    if _frontend_dist is None:
        return PlainTextResponse("Frontend not built", status_code=404)

    # Try to serve the requested static file
    path = request.path_params.get("full_path", "")
    file_path = _frontend_dist / path
    if file_path.is_file():
        return PlainTextResponse(
            file_path.read_bytes(),
            media_type=_guess_media_type(str(file_path)),
        )

    # Fall back to index.html for client-side routing
    index_file = _frontend_dist / "index.html"
    if index_file.exists():
        return HTMLResponse(index_file.read_text(encoding="utf-8"))

    return PlainTextResponse("Not Found", status_code=404)


def _guess_media_type(path: str) -> str:
    """Guess MIME type from file extension."""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    types = {
        "html": "text/html",
        "css": "text/css",
        "js": "application/javascript",
        "json": "application/json",
        "svg": "image/svg+xml",
        "png": "image/png",
        "jpg": "image/jpeg",
        "ico": "image/x-icon",
        "woff": "font/woff",
        "woff2": "font/woff2",
    }
    return types.get(ext, "application/octet-stream")
