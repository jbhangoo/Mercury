"""
Database Update Orchestrator for loading XRS RDR observations into existing PostGIS records
"""
from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

import numpy as np
from sqlalchemy.engine import Engine

from server.app.db.access import db_xrs_update

from .consts import (
    LOADER_VERSION,
    OPTIONAL_COLUMNS,
    OWN_COLUMNS,
    REQUIRED_COLUMNS,
    SPECTRA,
)
from .rdr_reader import RDRReader
from .rdr_parser import (
    build_json_column,
    calculate_center_lonlat,
    clean_value,
    parse_truthy,
    parse_utc,
)

log = logging.getLogger("rdr_updater")


class RDRUpdater:
    """Updates XRS RDR observation files into PostgreSQL using SQLAlchemy."""

    def __init__(
        self,
        engine: Engine,
        *,
        keep_housekeeping: bool = True,
        reader: RDRReader | None = None
    ):
        self.engine = engine
        self.keep_housekeeping = keep_housekeeping
        self.reader = reader or RDRReader()

    def load_file(