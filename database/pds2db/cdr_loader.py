"""
Database Ingestion Orchestrator for loading XRS CDR observations into PostGIS.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

import numpy as np
from sqlalchemy.engine import Engine

from .consts import (
    INSERT_SQL,
    LOADER_VERSION,
    OPTIONAL_COLUMNS,
    OWN_COLUMNS,
    REQUIRED_COLUMNS,
    SPECTRA,
)
from .cdr_reader import CDRReader
from .cdr_parser import (
    build_json_column,
    calculate_center_lonlat,
    clean_value,
    parse_truthy,
    parse_utc,
)

log = logging.getLogger("cdr_loader")


def _build_records(rows: np.ndarray, source_file: str, keep_housekeeping: bool):
    """Generator converting NumPy structured array rows to dictionary payloads for PostgreSQL."""
    names = set(rows.dtype.names)
    missing = [n for n in REQUIRED_COLUMNS if n not in names]
    if missing:
        raise ValueError(f"{source_file}: label lacks required columns: {missing}")
        
    met = rows["met"].tolist()
    if len(set(met)) != len(met):
        raise ValueError(f"{source_file}: duplicate MET values found in file")

    start = parse_utc(rows["utc"])
    seconds = rows["actual_integration_time"].tolist()
    lon, lat = calculate_center_lonlat(rows)
    intersection = parse_truthy(rows["intersection"]).tolist()
    flare = parse_truthy(rows["solar_flare_detected"]).tolist()
    
    columns = {
        k: rows[k].tolist() for k in ("orbit_number", "fov_status", "data_quality", *SPECTRA)
    }
    optional = {
        k: ([clean_value(v) for v in rows[k].tolist()] if k in names else [None] * len(rows))
        for k in OPTIONAL_COLUMNS
    }
    
    if keep_housekeeping:
        hk_names = [n for n in rows.dtype.names if n not in OWN_COLUMNS and "spare" not in n]
        hk = {n: build_json_column(rows[n]) for n in hk_names}
    else:
        hk = {}

    for i in range(len(rows)):
        yield {
            "source_file": source_file,
            "source_id": str(met[i]),
            "met": met[i],
            "orbit_number": columns["orbit_number"][i],
            "observed_start": start[i],
            "observed_end": start[i] + timedelta(seconds=int(seconds[i])),
            "fov_status": columns["fov_status"][i],
            "intersection": intersection[i],
            "data_quality": columns["data_quality"][i],
            "lon": lon[i],
            "lat": lat[i],
            "scalt": optional["scalt"][i],
            "solar_flare_detected": flare[i],
            "solar_monitor_rate": optional["solar_monitor_rate"][i],
            "solar_monitor_spect_shift": optional["solar_monitor_spect_shift"][i],
            **{target: columns[source][i] for source, target in SPECTRA.items()},
            "housekeeping": {n: hk[n][i] for n in hk} if keep_housekeeping else {},
            "processing_version": LOADER_VERSION,
        }


class CDRLoader:
    """Loads XRS CDR observation files into PostgreSQL using SQLAlchemy."""

    def __init__(
        self,
        engine: Engine,
        *,
        keep_housekeeping: bool = True,
        reader: CDRReader | None = None
    ):
        self.engine = engine
        self.keep_housekeeping = keep_housekeeping
        self.reader = reader or CDRReader()

    def load_file(
        self,
        dat_path: str | Path,
        *,
        xml_path: str | Path | None = None,
        keep_housekeeping: bool | None = None
    ) -> int:
        """Loads a single CDR .dat file in a single transaction."""
        dat_path = Path(dat_path)
        rows = self.reader.read(dat_path, xml_path)
        keep = self.keep_housekeeping if keep_housekeeping is None else keep_housekeeping
        
        records = list(_build_records(rows, dat_path.name.lower(), keep))
        
        with self.engine.begin() as connection:
            connection.execute(INSERT_SQL, records)
            
        return len(records)

    def load_tree(self, root: str | Path, *, keep_housekeeping: bool | None = None):
        """Recursively finds and loads all xrscdr*.dat files under root."""
        files = sorted(
            p for p in Path(root).rglob("*")
            if p.suffix.lower() == ".dat" and p.name.lower().startswith("xrscdr")
        )
        total, failures = 0, []
        
        for number, path in enumerate(files, 1):
            try:
                total += self.load_file(path, keep_housekeeping=keep_housekeeping)
            except Exception as exc:
                log.error("%s: %s", path, exc)
                failures.append((str(path), str(exc)))
                
            if number % 100 == 0 or number == len(files):
                log.info("%d/%d files processed, %d total records loaded", number, len(files), total)
                
        return total, failures