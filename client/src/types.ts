/** Shape returned by GET /api/xrs?lon=&lat= */
export interface XrsDetailPayload {
    aggregatedValue: number;
    solarIntensity: number;
    composition: string;
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