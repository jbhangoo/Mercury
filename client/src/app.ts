import { Deck, OrthographicView } from '@deck.gl/core';

import { buildMapLayer } from './map.ts';
import { buildReferenceLayer, toGeographicLatitude } from './coordinates.ts';
import { handleSurfaceClick, handleSurfaceHover } from './handlers.ts';
import { buildSelectionLayer } from './selection.ts';
import type { DeckPickingInfo } from './types.ts';

const mapLayer = buildMapLayer((info: DeckPickingInfo<unknown>) => {
    if (!info.coordinate) return;
    const [lon, pickedLatitude] = info.coordinate;
    showSelection({ lon, lat: toGeographicLatitude(pickedLatitude) });
    void handleSurfaceClick(info);
});
const referenceLayer = buildReferenceLayer();

const deckInstance = new Deck({
    parent: document.getElementById('map-container') as HTMLDivElement,
    views: new OrthographicView({ id: 'mercury-view' }),
    getTooltip: ({ coordinate }) =>  handleSurfaceHover(coordinate),
    initialViewState: {
        target: [0, 0, 0],
        zoom: 2
    },
    controller: true
});

function showSelection(selection: { lon: number; lat: number } | null): void {
    deckInstance.setProps({ layers: [mapLayer, referenceLayer, buildSelectionLayer(selection)] });
}

showSelection(null);
