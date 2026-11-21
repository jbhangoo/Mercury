export type SpectrumName =
    | 'gpc1_mg_spectrum'
    | 'gpc2_al_spectrum'
    | 'gpc3_un_spectrum'
    | 'solar_mon_spectrum';

export type SpectraByName = Record<SpectrumName, Array<number | null> | null>;

/** Exposure-normalized spectra returned by GET /api/xrs?lon=&lat=. */
export interface XrsSpectraPayload {
    lon: number;
    lat: number;
    radius_km: number;
    flare_only?: boolean;
    observation_count: number;
    /** Observations that had a usable solar monitor rate and integration time. */
    observations_used?: number;
    units?: string;
    spectra: SpectraByName;
    /** Poisson error of each value in `spectra`. */
    spectra_error?: SpectraByName;
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