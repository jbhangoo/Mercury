/** Weighted-average spectra returned by GET /api/xrs?lon=&lat=. */
export interface XrsSpectraPayload {
    lon: number;
    lat: number;
    radius_km: number;
    observation_count: number;
    spectra: {
        gpc1_mg_spectrum: Array<number | null> | null;
        gpc2_al_spectrum: Array<number | null> | null;
        gpc3_un_spectrum: Array<number | null> | null;
        solar_mon_spectrum: Array<number | null> | null;
    };
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
