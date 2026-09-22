"""
backend/app/main.py
───────────────────
FastAPI application factory for the Reproductive Health Assistant.
Integrates API routers, CORS middleware, and mounts static React frontend.
"""

import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.app.core.config import settings
from backend.app.api.router import api_router

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.PROJECT_DESCRIPTION,
        version=settings.VERSION,
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include REST & WebSocket API Routers
    app.include_router(api_router)

    # Mount Frontend Static Assets (if dist exists)
    frontend_dist = settings.FRONTEND_DIST_DIR
    assets_dir = frontend_dist / "assets"
    index_file = frontend_dist / "index.html"

    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/")
    async def root():
        if index_file.exists():
            return FileResponse(str(index_file))
        return {
            "message": "Reproductive Health Assistant API is running.",
            "frontend_status": "Frontend build (dist) not found. Run 'npm run build' in frontend directory.",
            "docs": "/docs",
        }

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # Exclude API endpoints, Swagger docs, or WebSocket prefixes
        if full_path.startswith(("api", "ws", "docs", "openapi.json", "redoc")):
            return None
        if index_file.exists():
            return FileResponse(str(index_file))
        return {"error": "Not Found"}

    return app

app = create_app()
