import { Deck, OrthographicView } from '@deck.gl/core';

import { buildMapLayer } from './map.ts';
import { buildReferenceLayer } from './coordinates.ts';
import { handleSurfaceHover } from './handlers.ts';

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

deckInstance.setProps({ layers: [buildMapLayer(), buildReferenceLayer()] });