from fastapi import FastAPI

from .xrs import xrs_router
from .tile import tile_router

def register_routes(app: FastAPI) -> None:
    app.include_router(xrs_router, prefix="/api")
    app.include_router(tile_router, prefix="/api")
