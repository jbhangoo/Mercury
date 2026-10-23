"""
Database update orchestrator for loading XRS RDR footprints into existing xrs rows.

A footprint file does not create observations. It belongs to a CDR row that must already
be loaded, found by the footprint's MET (with its start time as a cross-check). The
footprint is reduced to one number, the radius of the circle around the row's boresight
point that lies inside the footprint (see rdr_parser), and that radius and the footprint's
spacecraft clock partition are written to the row.

Footprints that cannot be applied are reported rather than failing the run:

    unmatched          no CDR row has this MET at this time (load that day's CDR file first)
    no_boresight       the row's boresight misses the planet, so there is no point to measure from
    boresight_outside  the boresight point is not inside the footprint's perimeter

Only unreadable files and database errors raise.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import Engine

from server.app.db.access import db_xrs_find_for_footprint, db_xrs_set_footprint

from .consts import FOOTPRINT_APPLIED, FOOTPRINT_UPDATED
from .consts import FOOTPRINT_UNCHANGED, FOOTPRINT_UNMATCHED, FOOTPRINT_NO_BORESIGHT, FOOTPRINT_BORESIGHT_OUTSIDE
from .rdr_parser import footprint_radius
from .rdr_reader import RDRReader

log = logging.getLogger("rdr_updater")


@dataclass(frozen=True)
class FootprintUpdate:
    """What happened to one footprint file."""
    source_file: str
    status: int                          # Bitmap: "updated", "unchanged" or one of FOOTPRINT_PROBLEM
    radius_km: float | None = None       # the radius measured (None if it could not be)
    offset_seconds: float | None = None  # CDR row start minus footprint label start

    @property
    def applied(self) -> bool:
        return self.status & FOOTPRINT_APPLIED

    @property
    def summary(self) -> str:
        if self.status & FOOTPRINT_UPDATED:
            return f"radius {self.radius_km:.1f} km stored"
        if self.status & FOOTPRINT_UNCHANGED:
            return f"already loaded (radius {self.radius_km:.1f} km), skipped"
        if self.status & FOOTPRINT_UNMATCHED:
            return "no CDR data for this MET and start time"
        if self.status & FOOTPRINT_NO_BORESIGHT:
            return "instrument boresight off-planet. Do not record."
        if self.status & FOOTPRINT_BORESIGHT_OUTSIDE:
            return "instrument angle too oblique. Do not record."
        return "UNRECOGNIZED RESULT!"


class RDRUpdater:
    """Applies XRS RDR footprint files to xrs rows using SQLAlchemy."""

    def __init__(self, engine: Engine, *, reader: RDRReader | None = None):
        self.engine = engine
        self.reader = reader or RDRReader()

    def update_from_file(
        self,
        csv_path: str | Path,
        *,
        xml_path: str | Path | None = None,
        force: bool = False,
    ) -> FootprintUpdate:
        """Applies one footprint file in a single transaction.

        A footprint whose radius and partition are already stored is skipped without a write
        unless force is set."""
        csv_path = Path(csv_path)
        footprint = self.reader.read_footprint(csv_path, xml_path)
        if footprint.start_time is None:
            raise ValueError(f"{csv_path.name}: the label has no start time to match the CDR row with")
        name = csv_path.name.lower()

        with self.engine.begin() as connection:
            row = db_xrs_find_for_footprint(connection, footprint.met, footprint.start_time)
            if row is None:
                return FootprintUpdate(name, FOOTPRINT_UNMATCHED)
            offset = (row["observed_start"] - footprint.start_time).total_seconds()
            if row["boresight_lat"] is None:
                return FootprintUpdate(name, FOOTPRINT_NO_BORESIGHT, offset_seconds=offset)

            measured = footprint_radius(row["boresight_lat"], row["boresight_lon"], footprint.vertices)
            if not measured.inside:
                return FootprintUpdate(name, FOOTPRINT_BORESIGHT_OUTSIDE, measured.radius_km, offset)

            stored = row["footprint_radius_km"]
            if (not force and stored is not None and row["sclk_partition"] == footprint.partition
                    and math.isclose(stored, measured.radius_km, rel_tol=1e-6, abs_tol=1e-4)):
                return FootprintUpdate(name, FOOTPRINT_UNCHANGED, stored, offset)

            db_xrs_set_footprint(connection, row["id"], footprint.partition, measured.radius_km)
            return FootprintUpdate(name, FOOTPRINT_UPDATED, measured.radius_km, offset)