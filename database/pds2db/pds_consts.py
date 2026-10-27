LOADER_VERSION = "cdr-loader-2"
MERCURY_RADIUS_KM = 2439.4
RADIUS_TOLERANCE_KM = 50.0

SPECTRA = {
    "gpc1_mg_spectrum_10_253": "gpc1_mg_spectrum",
    "gpc2_al_spectrum_10_253": "gpc2_al_spectrum",
    "gpc3_un_spectrum_10_253": "gpc3_un_spectrum",
    "solar_mon_spectrum_23_253": "solar_mon_spectrum",
}

# The loader will load the following columns if they are present in the CDR table 
# No other columns will be loaded, even if they are present in the CDR table.

# Columns that must be present in the CDR table for the loader to work
REQUIRED_COLUMNS = (
    "met", "orbit_number", "utc", "actual_integration_time", "fov_status", "intersection",
    "data_quality", "solar_flare_detected",
    "instr_boresight_mercury_x", "instr_boresight_mercury_y", "instr_boresight_mercury_z",
    *SPECTRA,
)

# Columns that are optional and will be loaded if present.  
OPTIONAL_COLUMNS = ("scalt", "solar_monitor_rate", "solar_monitor_spect_shift")

# 
OWN_COLUMNS = {
    "met", "orbit_number", "fov_status", "intersection", "data_quality", "solar_flare_detected",
    "scalt", "solar_monitor_rate", "solar_monitor_spect_shift", *SPECTRA,
}

# Outcomes of applying a footprint file to its CDR row (see rdr_updater).
FOOTPRINT_UPDATED = 0x80
FOOTPRINT_UNCHANGED = 0x40
FOOTPRINT_APPLIED = FOOTPRINT_UPDATED | FOOTPRINT_UNCHANGED

FOOTPRINT_UNMATCHED = 0x01
FOOTPRINT_NO_BORESIGHT = 0x02
FOOTPRINT_BORESIGHT_OUTSIDE = 0x04
FOOTPRINT_AMBIGUOUS = 0x08   # multiple nearby CDR rows with no unique exact-MET match
FOOTPRINT_PROBLEM = FOOTPRINT_UNMATCHED | FOOTPRINT_NO_BORESIGHT | FOOTPRINT_BORESIGHT_OUTSIDE | FOOTPRINT_AMBIGUOUS

# Informational flag, combined with an outcome above: a unique CDR row was matched by start time
# and its MET differs from the footprint's MET (see rdr_updater).
FOOTPRINT_MATCHED_BY_TIME = 0x20

{
    FOOTPRINT_UNMATCHED: "no CDR row with this MET and start time",
    FOOTPRINT_NO_BORESIGHT: "the CDR row has no boresight point (it missed the planet)",
    FOOTPRINT_BORESIGHT_OUTSIDE: "the boresight point is not inside the footprint",
}


# DATA_QUALITY_BITS
DQ_LENGTH_MISMATCH_PROBLEM = 1 << 0
FOOTPRINT_STATUS = {DQ_LENGTH_MISMATCH_PROBLEM: "data quality length mismatch",}