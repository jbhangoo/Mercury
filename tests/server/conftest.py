import asyncio

import httpx
import pytest
from fastapi import FastAPI

from main import app


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
def client() -> SyncASGIClient:
    return SyncASGIClient(app)