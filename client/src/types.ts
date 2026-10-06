/** One XRS observation returned by GET /api/xrs?lon=&lat=. */
export interface XrsObservationPayload {
    id: number;
    source_file: string;
    met: number;
    orbit_number: number;
    observed_start: string;
    observed_end: string;
    fov_status: number;
    intersection: boolean;
    data_quality: number;
    center_lon: number | null;
    center_lat: number | null;
    spacecraft_altitude_km: number | null;
    solar_flare_detected: boolean;
    solar_monitor_rate: number | null;
    solar_monitor_spect_shift: number | null;
    solar_intensity: number | null;
    solar_intensity_source: string | null;
    gpc1_mg_spectrum: number[] | null;
    gpc2_al_spectrum: number[] | null;
    gpc3_un_spectrum: number[] | null;
    solar_mon_spectrum: number[] | null;
    housekeeping: Record<string, unknown>;
}

/** Shape returned by GET /api/xrs?lon=&lat=. */
export interface XrsDetailPayload {
    lon: number;
    lat: number;
    observations: XrsObservationPayload[];
    has_more: boolean;
}

/** Information payload provided by Deck.gl event handlers (hover/click).
 * Under OrthographicView, info.coordinate is [x, y] where x = longitude
 * (East, -180..180) and y = latitude (-90..90). */
export interface DeckPickingInfo<T> {
    object?: T;
    coordinate?: number[];
    x: number;
    y: number;
}