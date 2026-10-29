from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from auth import get_current_user
from store import Store

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")


def create_app(store: Store | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = store or Store()
        yield

    app = FastAPI(title="Kirjapäiväkirja", lifespan=lifespan)

    @app.get("/api/me")
    def me(user: dict = Depends(get_current_user)) -> dict:
        return {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
        }

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    return app


app = create_app()
