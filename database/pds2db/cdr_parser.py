import math
from datetime import datetime, timezone
import numpy as np
from .consts import MERCURY_RADIUS_KM, RADIUS_TOLERANCE_KM

def parse_truthy(column: np.ndarray) -> np.ndarray:
    if column.dtype.kind in "biu":
        return column != 0
    if column.dtype.kind == "S":
        return np.isin(np.char.upper(np.char.strip(column)), [b"1", b"T", b"TRUE", b"Y"])
    raise ValueError(f"cannot interpret dtype {column.dtype} as boolean")

def parse_utc(column: np.ndarray) -> list[datetime]:
    out = []
    for raw in column.tolist():
        text_val = raw.decode("ascii").strip()
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y %m %d %H:%M:%S.%f",
            "%Y %m %d %H:%M:%S",
        ):
            try:
                out.append(datetime.strptime(text_val, fmt).replace(tzinfo=timezone.utc))
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"unparseable UTC value {text_val!r}")
    return out

def calculate_center_lonlat(rows: np.ndarray):
    x, y, z = (rows[f"instr_boresight_mercury_{axis}"].astype(np.float64) for axis in "xyz")
    radius = np.sqrt(x * x + y * y + z * z)
    with np.errstate(invalid="ignore", divide="ignore"):
        lon = np.degrees(np.arctan2(y, x))
        lat = np.degrees(np.arcsin(np.clip(z / radius, -1.0, 1.0)))
    usable = (parse_truthy(rows["intersection"]) & np.isfinite(radius)
              & (np.abs(radius - MERCURY_RADIUS_KM) <= RADIUS_TOLERANCE_KM))
    
    lon_list = [float(v) if ok else None for v, ok in zip(lon.tolist(), usable.tolist())]
    lat_list = [float(v) if ok else None for v, ok in zip(lat.tolist(), usable.tolist())]
    return lon_list, lat_list

def clean_value(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, list):
        return [clean_value(v) for v in value]
    return value

def build_json_column(column: np.ndarray) -> list:
    kind = column.dtype.kind if not column.dtype.shape else column.dtype.base.kind
    if column.dtype.names:
        subs = {n: build_json_column(column[n]) for n in column.dtype.names}
        return [{n: subs[n][i] for n in subs} for i in range(len(column))]
    if kind == "S":
        return [v.decode("ascii", "replace").strip() for v in column.tolist()]
    return [clean_value(v) for v in column.tolist()]