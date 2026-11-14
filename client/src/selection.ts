import { ScatterplotLayer } from '@deck.gl/layers';

import { FLIP_Y_MATRIX } from './coordinates.ts';

export interface Selection {
    lon: number;
    lat: number;
}

/** A marker on the spot the user clicked. Not pickable, so clicks reach the basemap. */
export function buildSelectionLayer(selection: Selection | null): ScatterplotLayer<Selection> {
    return new ScatterplotLayer<Selection>({
        id: 'mercury-selection',
        modelMatrix: FLIP_Y_MATRIX,
        data: selection ? [selection] : [],
        pickable: false,
        getPosition: (d) => [d.lon, d.lat],
        getRadius: 6,
        radiusUnits: 'pixels',
        getFillColor: [100, 255, 218, 255],
        stroked: true,
        getLineColor: [0, 0, 0, 255],
        getLineWidth: 2,
        lineWidthUnits: 'pixels'
    });
}
