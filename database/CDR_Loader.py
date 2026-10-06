"""
Load MESSENGER XRS CDR day files into the xrs table (see xrs_table.sql).

    from database.CDR_Loader import CDRLoader
    from database.CDR_Reader import CDRReader
    from database.sqlalchemy_db import create_database_engine

    engine = create_database_engine(dsn)
    try:
        loader = CDRLoader(engine, reader=CDRReader())
        total, failures = loader.load_tree("xrs_pds")
        # For a single day instead: loader.load_file("xrscdr2013101.dat")
    finally:
        engine.dispose()

Command line (loads every xrscdr*.dat under a folder, one transaction per file):

    python CDR_Loader.py xrs_pds/data --dsn postgresql://user:pw@localhost/mercury
    (DATABASE_URL is used when --dsn is omitted)

Loading is idempotent: a row is keyed on (source file, MET) and reloading
updates it in place. Columns filled by other steps (footprint, sclk_partition,
solar_intensity, solar_intensity_source) are never overwritten.

What goes where
- center: the CDR's Mercury-fixed boresight vector (km) converted to planetocentric
  east longitude in [-180, 180] and latitude. NULL when the pointing does not
  intersect the planet or the vector's length is not close to Mercury's radius.
- observed_start/observed_end: the CDR UTC column, plus the actual integration time.
- every CDR column not stored in its own column (spare columns excluded) goes
  into the housekeeping jsonb; NaN/infinity become null.
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

if __package__:
    from .CDR_Reader import CDRReader
    from .sqlalchemy_db import create_database_engine
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from database.CDR_Reader import CDRReader
    from database.sqlalchemy_db import create_database_engine

LOADER_VERSION = "cdr-loader-1"
SRID = 910001                      # Mercury lon/lat CRS registered by xrs_table.sql
MERCURY_RADIUS_KM = 2439.4
RADIUS_TOLERANCE_KM = 50.0         # boresight vectors farther than this from the sphere are rejected

SPECTRA = {                        # CDR column -> xrs column
    "gpc1_mg_spectrum_10_253": "gpc1_mg_spectrum",
    "gpc2_al_spectrum_10_253": "gpc2_al_spectrum",
    "gpc3_un_spectrum_10_253": "gpc3_un_spectrum",
    "solar_mon_spectrum_23_253": "solar_mon_spectrum",
}
REQUIRED = (
    "met", "orbit_number", "utc", "actual_integration_time", "fov_status", "intersection",
    "data_quality", "solar_flare_detected",
    "instr_boresight_mercury_x", "instr_boresight_mercury_y", "instr_boresight_mercury_z",
    *SPECTRA,
)
OPTIONAL = ("scalt", "solar_monitor_rate", "solar_monitor_spect_shift")
OWN_COLUMN = {                     # CDR columns stored in their own xrs column (not duplicated in housekeeping)
    "met", "orbit_number", "fov_status", "intersection", "data_quality", "solar_flare_detected",
    "scalt", "solar_monitor_rate", "solar_monitor_spect_shift", *SPECTRA,
}

INSERT_SQL = text(f"""
INSERT INTO xrs (
    source_file, source_id, met, orbit_number, observed_start, observed_end,
    fov_status, intersection, data_quality, center, spacecraft_altitude_km,
    solar_flare_detected, solar_monitor_rate, solar_monitor_spect_shift,
    gpc1_mg_spectrum, gpc2_al_spectrum, gpc3_un_spectrum, solar_mon_spectrum,
    housekeeping, processing_version
) VALUES (
    :source_file, :source_id, :met, :orbit_number, :observed_start, :observed_end,
    :fov_status, :intersection, :data_quality,
    CASE WHEN CAST(:lon AS double precision) IS NULL THEN NULL
         ELSE ST_SetSRID(ST_MakePoint(CAST(:lon AS double precision),
                                      CAST(:lat AS double precision)), {SRID}) END,
    :scalt, :solar_flare_detected, :solar_monitor_rate, :solar_monitor_spect_shift,
    CAST(:gpc1_mg_spectrum AS integer[]), CAST(:gpc2_al_spectrum AS integer[]),
    CAST(:gpc3_un_spectrum AS integer[]), CAST(:solar_mon_spectrum AS integer[]),
    :housekeeping, :processing_version
)
ON CONFLICT (source_file, source_id) DO UPDATE SET
    met = EXCLUDED.met, orbit_number = EXCLUDED.orbit_number,
    observed_start = EXCLUDED.observed_start, observed_end = EXCLUDED.observed_end,
    fov_status = EXCLUDED.fov_status, intersection = EXCLUDED.intersection,
    data_quality = EXCLUDED.data_quality, center = EXCLUDED.center,
    spacecraft_altitude_km = EXCLUDED.spacecraft_altitude_km,
    solar_flare_detected = EXCLUDED.solar_flare_detected,
    solar_monitor_rate = EXCLUDED.solar_monitor_rate,
    solar_monitor_spect_shift = EXCLUDED.solar_monitor_spect_shift,
    gpc1_mg_spectrum = EXCLUDED.gpc1_mg_spectrum, gpc2_al_spectrum = EXCLUDED.gpc2_al_spectrum,
    gpc3_un_spectrum = EXCLUDED.gpc3_un_spectrum, solar_mon_spectrum = EXCLUDED.solar_mon_spectrum,
    housekeeping = EXCLUDED.housekeeping, processing_version = EXCLUDED.processing_version
""").bindparams(bindparam("housekeeping", type_=JSONB))

log = logging.getLogger("cdr_loader")


def _truthy(column: np.ndarray) -> np.ndarray:
    """Boolean array from numeric (0/1) or text (b'1', b'T', b'TRUE') encodings."""
    if column.dtype.kind in "biu":
        return column != 0
    if column.dtype.kind == "S":
        return np.isin(np.char.upper(np.char.strip(column)), [b"1", b"T", b"TRUE", b"Y"])
    raise ValueError(f"cannot interpret dtype {column.dtype} as boolean")


def _parse_utc(column: np.ndarray) -> list[datetime]:
    out = []
    for raw in column.tolist():
        text = raw.decode("ascii").strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                out.append(datetime.strptime(text, fmt).replace(tzinfo=timezone.utc))
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"unparseable UTC value {text!r}")
    return out


def _center_lonlat(rows: np.ndarray):
    """Lists of (lon, lat) in degrees, None where the boresight is unusable."""
    x, y, z = (rows[f"instr_boresight_mercury_{axis}"].astype(np.float64) for axis in "xyz")
    radius = np.sqrt(x * x + y * y + z * z)
    with np.errstate(invalid="ignore", divide="ignore"):
        lon = np.degrees(np.arctan2(y, x))                       # east-positive, [-180, 180]
        lat = np.degrees(np.arcsin(np.clip(z / radius, -1.0, 1.0)))
    usable = (_truthy(rows["intersection"]) & np.isfinite(radius)
              & (np.abs(radius - MERCURY_RADIUS_KM) <= RADIUS_TOLERANCE_KM))
    to_list = lambda a: [float(v) if ok else None for v, ok in zip(a.tolist(), usable.tolist())]
    return to_list(lon), to_list(lat)


def _clean(value):
    """JSON-safe copy: non-finite floats -> None, recursing into lists."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _json_column(column: np.ndarray) -> list:
    """One JSON-safe Python value per row."""
    kind = column.dtype.kind if not column.dtype.shape else column.dtype.base.kind
    if column.dtype.names:                                       # structured: dict per row
        subs = {n: _json_column(column[n]) for n in column.dtype.names}
        return [{n: subs[n][i] for n in subs} for i in range(len(column))]
    if kind == "S":
        return [v.decode("ascii", "replace").strip() for v in column.tolist()]
    return [_clean(v) for v in column.tolist()]


def _records(rows: np.ndarray, source_file: str, keep_housekeeping: bool):
    names = set(rows.dtype.names)
    missing = [n for n in REQUIRED if n not in names]
    if missing:
        raise ValueError(f"{source_file}: label lacks required columns {missing}")
    met = rows["met"].tolist()
    if len(set(met)) != len(met):
        raise ValueError(f"{source_file}: duplicate MET values; MET is used as the row key")

    start = _parse_utc(rows["utc"])
    seconds = rows["actual_integration_time"].tolist()
    lon, lat = _center_lonlat(rows)
    intersection = _truthy(rows["intersection"]).tolist()
    flare = _truthy(rows["solar_flare_detected"]).tolist()
    columns = {k: rows[k].tolist() for k in
               ("orbit_number", "fov_status", "data_quality", *SPECTRA)}
    optional = {k: ([_clean(v) for v in rows[k].tolist()] if k in names else [None] * len(rows))
                for k in OPTIONAL}
    if keep_housekeeping:
        hk_names = [n for n in rows.dtype.names if n not in OWN_COLUMN and "spare" not in n]
        hk = {n: _json_column(rows[n]) for n in hk_names}

    for i in range(len(rows)):
        yield {
            "source_file": source_file, "source_id": str(met[i]), "met": met[i],
            "orbit_number": columns["orbit_number"][i],
            "observed_start": start[i],
            "observed_end": start[i] + timedelta(seconds=int(seconds[i])),
            "fov_status": columns["fov_status"][i], "intersection": intersection[i],
            "data_quality": columns["data_quality"][i], "lon": lon[i], "lat": lat[i],
            "scalt": optional["scalt"][i], "solar_flare_detected": flare[i],
            "solar_monitor_rate": optional["solar_monitor_rate"][i],
            "solar_monitor_spect_shift": optional["solar_monitor_spect_shift"][i],
            **{target: columns[source][i] for source, target in SPECTRA.items()},
            "housekeeping": {n: hk[n][i] for n in hk} if keep_housekeeping else {},
            "processing_version": LOADER_VERSION,
        }


class CDRLoader:
    """Load one CDR file or a directory tree using a SQLAlchemy engine.

    Example::

        reader = CDRReader()
        engine = create_database_engine(dsn)
        loader = CDRLoader(engine, reader=reader)
        records, failures = loader.load_tree("xrs_pds")
        engine.dispose()
    """

    def __init__(self, engine: Engine, *, keep_housekeeping: bool = True,
                 reader: CDRReader | None = None):
        self.engine = engine
        self.keep_housekeeping = keep_housekeeping
        self.reader = reader or CDRReader()

    def load_file(self, dat_path, *, xml_path=None,
                  keep_housekeeping: bool | None = None) -> int:
        """Write one CDR day's records in a single transaction."""
        dat_path = Path(dat_path)
        rows = self.reader.read(dat_path, xml_path)
        keep = self.keep_housekeeping if keep_housekeeping is None else keep_housekeeping
        records = list(_records(rows, dat_path.name.lower(), keep))
        with self.engine.begin() as connection:
            connection.execute(INSERT_SQL, records)
        return len(records)

    def load_tree(self, root, *, keep_housekeeping: bool | None = None):
        """Load xrscdr*.dat files; log and report failures while continuing."""
        files = sorted(p for p in Path(root).rglob("*")
                       if p.suffix.lower() == ".dat" and p.name.lower().startswith("xrscdr"))
        total, failures = 0, []
        for number, path in enumerate(files, 1):
            try:
                total += self.load_file(path, keep_housekeeping=keep_housekeeping)
            except Exception as exc:                             # keep going; report at the end
                log.error("%s: %s", path, exc)
                failures.append((str(path), str(exc)))
            if number % 100 == 0 or number == len(files):
                log.info("%d/%d files, %d records", number, len(files), total)
        return total, failures


def load_cdr_file(engine: Engine, dat_path, *, xml_path=None,
                  keep_housekeeping: bool = True) -> int:
    """Functional interface for loading one file."""
    return CDRLoader(engine, keep_housekeeping=keep_housekeeping).load_file(
        dat_path, xml_path=xml_path)


def load_cdr_tree(engine: Engine, root, *, keep_housekeeping: bool = True):
    """Functional interface for loading a tree (kept for compatibility)."""
    return CDRLoader(engine, keep_housekeeping=keep_housekeeping).load_tree(root)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Load XRS CDR day files into the xrs table.")
    ap.add_argument("root", help="folder containing xrscdr*.dat files and their .xml labels")
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL"), help="Postgres connection string")
    ap.add_argument("--no-housekeeping", action="store_true", help="do not store the housekeeping jsonb")
    args = ap.parse_args(argv)
    if not args.dsn:
        ap.error("give --dsn or set DATABASE_URL")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = create_database_engine(args.dsn)
    try:
        loader = CDRLoader(engine, keep_housekeeping=not args.no_housekeeping)
        total, failures = loader.load_tree(args.root)
    finally:
        engine.dispose()
    print(f"{total} records loaded, {len(failures)} files failed")
    for path, error in failures:
        print(f"  FAILED {path}: {error}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())