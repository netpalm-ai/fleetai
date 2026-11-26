"""Auth ASGI app. The auth container and auth tests load this."""

from __future__ import annotations

from contextlib import asynccontextmanager

import db
from auth.routes import router as auth_router
from auth.service import Product
from auth.sessions import start_cleanup
from fastapi import FastAPI

DEFAULT_PRODUCT = Product(id="fleetai", name="FleetAI", signup_tier="free")

_cleanup_stop = None


def create_app(product: Product | None = None) -> FastAPI:
    chosen = product or DEFAULT_PRODUCT

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        global _cleanup_stop
        db.open_pool()
        if db.pool is not None:
            _cleanup_stop = start_cleanup()
        yield
        if _cleanup_stop is not None:
            _cleanup_stop.set()
            _cleanup_stop = None
        db.close_pool()

    app = FastAPI(title="netpalm-auth", version="0.1.0", lifespan=lifespan)
    app.state.auth_product = chosen
    app.include_router(auth_router, prefix="/auth")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": "auth"}

    return app


app = create_app()
