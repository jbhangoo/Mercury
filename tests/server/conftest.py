import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI

from main import app


class EmptyResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class EmptyConnection:
    def __init__(self, engine):
        self.engine = engine

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement, parameters):
        self.engine.last_query_parameters = parameters
        return EmptyResult(self.engine.rows)


class EmptyEngine:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.last_query_parameters = None

    @contextmanager
    def connect(self):
        yield EmptyConnection(self)


class SyncASGIClient:
    def __init__(self, app: FastAPI) -> None:
        self.app = app

    def get(self, url: str) -> httpx.Response:
        async def request() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                return await client.get(url)

        return asyncio.run(request())


@pytest.fixture
def client() -> Iterator[SyncASGIClient]:
    def mock_trek_response(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"\xff\xd8\xffmock-jpeg-data\xff\xd9",
            headers={"content-type": "image/jpeg"},
        )

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(mock_trek_response),
    )
    previous_engine = app.state.db_engine
    app.state.db_engine = EmptyEngine()
    app.state.http_client = http_client
    try:
        yield SyncASGIClient(app)
    finally:
        asyncio.run(http_client.aclose())
        del app.state.http_client
        app.state.db_engine = previous_engine