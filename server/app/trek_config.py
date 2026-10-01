"""
Mercury Trek WMTS configuration.

This used to live in the frontend (app.ts's TREK_CONFIG), but Trek's tile
server doesn't send CORS headers, so the browser can't fetch tiles from it
directly. This module now owns the real config, and app/routes/tile.py
proxies requests through this backend instead.

Values below are confirmed from actual browser network requests (not
guessed) — see the tile URLs in the browser console when this was still
being fetched client-side.
"""

#MERCURY_IMAGERY_URL = "https://trek.nasa.gov/tiles/Mercury/EQ/Mercury_MESSENGER_MDIS_Basemap_BDR_Mosaic_Global_665m"
MERCURY_IMAGERY_URL = "https://trek.nasa.gov/tiles/Mercury/EQ/Mercury_MESSENGER_MDIS_Basemap_EnhancedColor_Mosaic_Global_665m"
STYLE = "default"
TILE_MATRIX_SET = "default028mm"
FILE_EXTENSION = "jpg"

MIN_ZOOM = 0
MAX_ZOOM = 7

# Flip if imagery renders upside down (TileRow=0 at south instead of north)
FLIP_Y = False


def valid_tile_range(z: int) -> tuple[int, int]:
    """
    Valid (num_cols, num_rows) at zoom level z, given Trek's documented
    scheme: 2 cols x 1 row at z=0, doubling each axis per zoom level.
    """
    return (2 ** (z + 1), 2 ** z)


def is_valid_tile(x: int, y: int, z: int) -> bool:
    num_cols, num_rows = valid_tile_range(z)
    return 0 <= x < num_cols and 0 <= y < num_rows


def build_trek_tile_url(x: int, y: int, z: int) -> str:
    """
    Builds the real Trek WMTS tile URL. Caller is responsible for checking
    is_valid_tile() first — this does not validate.
    """
    _, num_rows = valid_tile_range(z)
    row = (num_rows - 1 - y) if FLIP_Y else y
    return f"{MERCURY_IMAGERY_URL}/1.0.0/{STYLE}/{TILE_MATRIX_SET}/{z}/{row}/{x}.{FILE_EXTENSION}"

def pick_trek_tile(west: float, south: float, east: float, north: float) -> tuple[int, int, int]:
    """
    Picks the real Trek TileMatrix/TileRow/TileCol that best covers a
    geographic bounding box (degrees). Not a true reprojection — deck.gl's
    own tile grid under OrthographicView has no relationship to Trek's
    real WMTS grid, so this picks the closest-matching real tile by scale
    and center point, accepting some stretch/misalignment at tile edges.
    Good enough for a visual overlay; not pixel-perfect.
    """
    width = east - west

    best_z, best_diff = MIN_ZOOM, float("inf")
    for z in range(MIN_ZOOM, MAX_ZOOM + 1):
        diff = abs(360 / (2 ** (z + 1)) - width)
        if diff < best_diff:
            best_z, best_diff = z, diff

    num_cols, num_rows = valid_tile_range(best_z)
    center_lon = (west + east) / 2
    center_lat = (south + north) / 2

    col = max(0, min(num_cols - 1, int((center_lon + 180) / 360 * num_cols)))
    # Trek's TileRow=0 is the northernmost row
    row = max(0, min(num_rows - 1, int((90 - center_lat) / 180 * num_rows)))

    return best_z, row, col