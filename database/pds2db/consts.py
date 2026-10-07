import math
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

LOADER_VERSION = "cdr-loader-1"
SRID = 910001
MERCURY_RADIUS_KM = 2439.4
RADIUS_TOLERANCE_KM = 50.0

SPECTRA = {
    "gpc1_mg_spectrum_10_253": "gpc1_mg_spectrum",
    "gpc2_al_spectrum_10_253": "gpc2_al_spectrum",
    "gpc3_un_spectrum_10_253": "gpc3_un_spectrum",
    "solar_mon_spectrum_23_253": "solar_mon_spectrum",
}

REQUIRED_COLUMNS = (
    "met", "orbit_number", "utc", "actual_integration_time", "fov_status", "intersection",
    "data_quality", "solar_flare_detected",
    "instr_boresight_mercury_x", "instr_boresight_mercury_y", "instr_boresight_mercury_z",
    *SPECTRA,
)

OPTIONAL_COLUMNS = ("scalt", "solar_monitor_rate", "solar_monitor_spect_shift")

OWN_COLUMNS = {
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
