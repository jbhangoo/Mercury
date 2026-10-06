from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.engine import Engine

from app.config import Config
from app.database import create_database_engine
from app.routes import register_routes


def create_app(engine: Engine | None = None) -> FastAPI:
    owns_engine = engine is None
    db_engine = engine if engine is not None else create_database_engine(Config.DATABASE_URL)

    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        app.state.http_client = httpx.AsyncClient(timeout=10.0)
        try:
            yield
        finally:
            await app.state.http_client.aclose()
            if owns_engine:
                db_engine.dispose()

    app = FastAPI(debug=Config.DEBUG, lifespan=app_lifespan)
    app.state.db_engine = db_engine

    app.add_middleware(
        CORSMiddleware,
        allow_origins=Config.CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_routes(app)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app