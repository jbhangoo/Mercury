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

from server.app.db.access import (
    db_xrs_find_for_footprint, db_xrs_find_for_footprint_by_time, db_xrs_nearest_by_time, db_xrs_set_footprint,
)

from .pds_consts import FOOTPRINT_APPLIED, FOOTPRINT_UPDATED
from .pds_consts import FOOTPRINT_UNCHANGED, FOOTPRINT_UNMATCHED, FOOTPRINT_NO_BORESIGHT, FOOTPRINT_BORESIGHT_OUTSIDE
from .pds_consts import FOOTPRINT_AMBIGUOUS, FOOTPRINT_MATCHED_BY_TIME
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
    note: str | None = None              # extra explanation, e.g. which CDR rows are near an unmatched footprint
    met_offset: int | None = None        # CDR row MET minus footprint MET (0 when they agree)
    row_id: int | None = None            # the xrs row the footprint was matched to, if any

    @property
    def applied(self) -> bool:
        return self.status & FOOTPRINT_APPLIED

    @property
    def matched_by_time(self) -> bool:
        return bool(self.status & FOOTPRINT_MATCHED_BY_TIME)

    @property
    def summary(self) -> str:
        by_time = (f" (matched by start time; the CDR row's MET is {self.met_offset:+d} from the footprint's)"
                   if self.matched_by_time else "")
        if self.status & FOOTPRINT_UPDATED:
            return f"radius {self.radius_km:.1f} km stored{by_time}"
        if self.status & FOOTPRINT_UNCHANGED:
            return f"already loaded (radius {self.radius_km:.1f} km), skipped{by_time}"
        if self.status & FOOTPRINT_AMBIGUOUS:
            return f"more than one CDR row starts at this time and none has this MET: {self.note}"
        if self.status & FOOTPRINT_UNMATCHED:
            text = "no CDR data for this MET and start time"
            return f"{text}: {self.note}" if self.note else text
        if self.status & FOOTPRINT_NO_BORESIGHT:
            return "instrument boresight off-planet. Do not record."
        if self.status & FOOTPRINT_BORESIGHT_OUTSIDE:
            return "instrument angle too oblique. Do not record."
        return "UNRECOGNIZED RESULT!"


def describe_nearby(footprint, nearby) -> str:
    """Says why a footprint found no CDR row, from the rows nearest to it in time."""
    start = footprint.start_time
    if not nearby:
        return (f"the table has no CDR rows within a day of {start:%Y-%m-%d %H:%M:%S} UTC; "
                f"is that day's CDR file loaded?")
    near = ", ".join(f"MET {r['met']} ({(r['observed_start'] - start).total_seconds():+.0f} s)" for r in nearby)
    return f"the footprint's MET is {footprint.met}; the nearest CDR rows by time are {near}"


class RDRUpdater:
    """Applies XRS RDR footprint files to xrs rows using SQLAlchemy."""

    def __init__(self, engine: Engine, *, reader: RDRReader | None = None, match_by_time: bool = False):
        """The SIS names the spacecraft clock count (MET) as the key that ties a footprint to its CDR row,
        with the UTC date only as a first filter, so a footprint matches the row with its MET.

        match_by_time: when no CDR row has the footprint's MET, fall back to the one row that starts at the
        footprint's start time (see FOOTPRINT_TIME_TOLERANCE). Use it only after checking, with the
        unmatched-footprint report, that the two clocks really differ. The result is flagged, and report()
        in load_rdr_records shows how the two MET values relate."""
        self.engine = engine
        self.reader = reader or RDRReader()
        self.match_by_time = match_by_time

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
            flags = 0
            if row is None and self.match_by_time:
                candidates = db_xrs_find_for_footprint_by_time(connection, footprint.start_time)
                if len(candidates) > 1:
                    near = ", ".join(f"MET {c['met']}" for c in candidates)
                    return FootprintUpdate(name, FOOTPRINT_AMBIGUOUS, note=f"{near} (footprint MET {footprint.met})")
                if candidates:
                    row, flags = candidates[0], FOOTPRINT_MATCHED_BY_TIME
            if row is None:
                nearby = db_xrs_nearest_by_time(connection, footprint.start_time)
                return FootprintUpdate(name, FOOTPRINT_UNMATCHED, note=describe_nearby(footprint, nearby))
            offset = (row["observed_start"] - footprint.start_time).total_seconds()
            met_offset = row["met"] - footprint.met
            if row["boresight_lat"] is None:
                return FootprintUpdate(name, FOOTPRINT_NO_BORESIGHT | flags, offset_seconds=offset,
                                       met_offset=met_offset, row_id=row["id"])

            measured = footprint_radius(row["boresight_lat"], row["boresight_lon"], footprint.vertices)
            if not measured.inside:
                return FootprintUpdate(name, FOOTPRINT_BORESIGHT_OUTSIDE | flags, measured.radius_km, offset,
                                       met_offset=met_offset, row_id=row["id"])

            stored = row["footprint_radius_km"]
            if (not force and stored is not None and row["sclk_partition"] == footprint.partition
                    and math.isclose(stored, measured.radius_km, rel_tol=1e-6, abs_tol=1e-4)):
                return FootprintUpdate(name, FOOTPRINT_UNCHANGED | flags, stored, offset, met_offset=met_offset,
                                       row_id=row["id"])

            db_xrs_set_footprint(connection, row["id"], footprint.partition, measured.radius_km)
            return FootprintUpdate(name, FOOTPRINT_UPDATED | flags, measured.radius_km, offset, met_offset=met_offset,
                                   row_id=row["id"])