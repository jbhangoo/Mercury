import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildMapLayer } from '../../client/src/map.ts';
import { XRS_API_BASE } from '../../client/src/config.ts';

// getTileData loads tiles with loaders.gl, which calls the global fetch.
// Stubbing fetch keeps the real code path but never touches the network.
function stubFetchFailing() {
    const fetchMock = vi.fn(async () => {
        throw new Error('network down');
    });
    vi.stubGlobal('fetch', fetchMock);
    vi.spyOn(console, 'error').mockImplementation(() => {});
    return fetchMock;
}

describe('buildMapLayer', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
    });

    it('is configured for the full Mercury extent and Trek zoom range', () => {
        const layer = buildMapLayer();
        expect(layer.props.extent).toEqual([-180, -90, 180, 90]);
        expect(layer.props.minZoom).toBe(0);
        expect(layer.props.maxZoom).toBe(7);
    });

    it('requests /mercury-tile with the tile bbox', async () => {
        const fetchMock = stubFetchFailing();
        const layer = buildMapLayer();

        await (layer.props.getTileData as any)({
            bbox: { left: -45, top: 0, right: 0, bottom: 45 }
        });

        const requested = String((fetchMock.mock.calls as any[][])[0][0]);
        expect(requested).toBe(`${XRS_API_BASE}/mercury-tile?west=-45&south=0&east=0&north=45`);
    });

    it('returns null instead of throwing when the tile fails to load', async () => {
        stubFetchFailing();
        const layer = buildMapLayer();

        const result = await (layer.props.getTileData as any)({
            bbox: { left: 0, top: 0, right: 1, bottom: 1 }
        });

        expect(result).toBeNull();
    });
});
