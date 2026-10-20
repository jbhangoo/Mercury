LOADER_VERSION = "cdr-loader-1"
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
