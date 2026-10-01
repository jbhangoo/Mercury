import { Matrix4 } from '@math.gl/core';
import { PathLayer } from '@deck.gl/layers';

/**
 * Black reference lines at key lat/lon positions: the equator, ±45°
 * latitude, the prime meridian, and ±90°/180° longitude. Not pickable —
 * clicks pass through to the basemap beneath for the XRS lookup.
 */
export function buildReferenceLayer(): PathLayer<any> {
    const latitudeLines = [-45, 0, 45].map((lat) => ({
        path: [[-180, lat], [180, lat]]
    }));
    const longitudeLines = [-180, -90, 0, 90, 180].map((lon) => ({
        path: [[lon, -90], [lon, 90]]
    }));

    return new PathLayer({
        id: 'mercury-reference',
        modelMatrix: FLIP_Y_MATRIX,
        data: [...latitudeLines, ...longitudeLines],
        pickable: false,
        getPath: (d: any) => d.path,
        getColor: [0, 0, 0, 255],
        getWidth: 1,
        widthUnits: 'pixels'
    });
}

/**
 * OrthographicView treats +y the same direction as screen-down, but
 * latitude increases upward — this flips rendering only (not picking or
 * any coordinate math elsewhere, which stay in true lon/lat) so north
 * actually renders at the top of the screen.
 */
export const FLIP_Y_MATRIX = new Matrix4().scale([1, -1, 1]);

export function toGeographicLatitude(pickedLatitude: number): number {
    return -pickedLatitude;
}

export function formatLongitude(lonEast: number): string {
    const hemisphere = lonEast >= 0 ? 'E' : 'W';
    return `${Math.abs(lonEast).toFixed(2)}° ${hemisphere}`;
}