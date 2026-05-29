"""FastAPI application for dreamulator."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

# Register routers
app.include_router(worlds_router)


@app.get("/api/health")
def health_check() -> dict:
    """Health check endpoint."""
    return {"ok": True, "service": "dreamulator"}
