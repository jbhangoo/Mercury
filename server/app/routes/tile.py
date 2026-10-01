import httpx
from fastapi import APIRouter, HTTPException, Request, Response

from app.trek_config import build_trek_tile_url, pick_trek_tile

tile_router = APIRouter()


@tile_router.get("/mercury-tile")
async def get_mercury_tile(
    west: float, south: float, east: float, north: float, request: Request
) -> Response:
    """
    Proxies Mercury Trek imagery for a geographic bounding box.

    Earlier versions took deck.gl's own {z}/{y}/{x} directly and forwarded
    it to Trek — wrong, since that index has no relationship to Trek's
    real tile grid under OrthographicView. This picks the closest real
    Trek tile by actual geography instead.
    """
    z, row, col = pick_trek_tile(west, south, east, north)
    url = build_trek_tile_url(col, row, z)

    client: httpx.AsyncClient = request.app.state.http_client
    try:
        resp = await client.get(url)
    except httpx.RequestError as err:
        print(f"Trek tile fetch failed for {z}/{row}/{col}: {type(err).__name__}: {err!r}")
        raise HTTPException(status_code=502) from err

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code)

    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type", "image/jpeg"),
        headers={"Cache-Control": "public, max-age=86400"},
    )