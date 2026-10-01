import { TileLayer } from '@deck.gl/geo-layers';
import { BitmapLayer } from '@deck.gl/layers';
import { load } from '@loaders.gl/core';
import { ImageLoader } from '@loaders.gl/images';

import { XRS_API_BASE, TREK_TILE_CONFIG } from './config.ts';
import { FLIP_Y_MATRIX } from './coordinates.ts';
import { handleSurfaceClick } from './handlers.ts';
import type { DeckPickingInfo } from './types.ts';

/**
 * The Mercury Trek basemap, as an image tile pyramid, proxied through our
 * own backend (see tile.py) to sidestep Trek's missing CORS headers and
 * to translate deck.gl's own tile grid into real Trek tiles by geography.
 */
export function buildMapLayer(): TileLayer<any> {
    return new TileLayer({
        id: 'mercury-map',
        modelMatrix: FLIP_Y_MATRIX,
        data: null,
        pickable: true,
        tileSize: 180,
        extent: [-180, -90, 180, 90],
        minZoom: TREK_TILE_CONFIG.minZoom,
        maxZoom: TREK_TILE_CONFIG.maxZoom,

        getTileData: async (props: any) => {
            const { left, top, right, bottom } = props.bbox;
            const url = `${XRS_API_BASE}/mercury-tile?west=${left}&south=${top}&east=${right}&north=${bottom}`;
            try {
                return await load(url, ImageLoader);
            } catch (err) {
                console.error(`Failed to load Mercury tile for bbox ${JSON.stringify(props.bbox)}:`, err);
                return null;
            }
        },

        renderSubLayers: (props: any) => {
            const { boundingBox } = props.tile;
            const [[west, south], [east, north]] = boundingBox;
            return new BitmapLayer(props, {
                data: undefined,
                image: props.data,
                bounds: [west, south, east, north]
            });
        },

        onClick: (info: DeckPickingInfo<unknown>) => { void handleSurfaceClick(info); }
    });
}