from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Config
from app.routes import register_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(timeout=10.0)
    yield
    await app.state.http_client.aclose()


def create_app() -> FastAPI:
    app = FastAPI(debug=Config.DEBUG, lifespan=lifespan)

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