import { afterEach, describe, expect, it, vi } from 'vitest';
import { handleSurfaceClick, handleSurfaceHover } from '../../client/src/handlers.ts';
import { XRS_API_BASE } from '../../client/src/config.ts';

describe('handleSurfaceHover', () => {
    it('returns an empty string when nothing is under the cursor', () => {
        expect(handleSurfaceHover(undefined)).toBe('');
    });

    it('flips the picked latitude and formats (lat, lon)', () => {
        // picked y is the negative of geographic latitude
        expect(handleSurfaceHover([80.5, -30])).toBe('(30.00, 80.50)');
    });
});

describe('handleSurfaceClick', () => {
    const panel = { innerHTML: '' };

    function stubBrowser(fetchImpl: (...args: any[]) => any) {
        panel.innerHTML = '';
        const fetchMock = vi.fn(fetchImpl);
        vi.stubGlobal('fetch', fetchMock);
        vi.stubGlobal('document', { getElementById: () => panel });
        return fetchMock;
    }

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('does nothing without a coordinate', async () => {
        const fetchMock = stubBrowser(async () => ({}));
        await handleSurfaceClick({ x: 0, y: 0 });
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('requests XRS data with geographic lat/lon and renders summarized spectra', async () => {
        const payload = {
            lon: -80.5,
            lat: 30,
            radius_km: 0,
            observation_count: 2,
            spectra: {
                gpc1_mg_spectrum: [1.25, 2.5],
                gpc2_al_spectrum: [4],
                gpc3_un_spectrum: null,
                solar_mon_spectrum: [0.5, 1]
            }
        };
        const fetchMock = stubBrowser(async () => ({ ok: true, json: async () => payload }));

        await handleSurfaceClick({ x: 0, y: 0, coordinate: [-80.5, -30] });

        expect(fetchMock).toHaveBeenCalledWith(`${XRS_API_BASE}/xrs?lon=-80.5&lat=30`);
        expect(panel.innerHTML).toContain('30.00° N, 80.50° W');
        expect(panel.innerHTML).toContain('<strong>Matching observations:</strong> 2');
        expect(panel.innerHTML).toContain('gpc1_mg_spectrum');
        expect(panel.innerHTML).toContain('3.75 mean counts');
        expect(panel.innerHTML).toContain('Unavailable');
        expect(panel.innerHTML).toContain('Spatially weighted mean spectra');
    });

    it('explains when no observation footprint covers the selected position', async () => {
        stubBrowser(async () => ({
            ok: true,
            json: async () => ({
                lon: 10,
                lat: 10,
                observation_count: 0,
                spectra: {
                    gpc1_mg_spectrum: null,
                    gpc2_al_spectrum: null,
                    gpc3_un_spectrum: null,
                    solar_mon_spectrum: null
                }
            })
        }));

        await handleSurfaceClick({ x: 0, y: 0, coordinate: [10, 10] });

        expect(panel.innerHTML).toContain('No XRS observations have a footprint covering this position.');
    });

    it('ignores a response that arrives after a newer click', async () => {
        let resolveFirst: (value: any) => void = () => {};
        const slow = new Promise(resolve => { resolveFirst = resolve; });
        let call = 0;
        stubBrowser(() => (++call === 1
            ? slow
            : Promise.resolve({ ok: true, json: async () => ({ lon: 1, lat: 1, observation_count: 0, spectra: {} }) })));

        const first = handleSurfaceClick({ x: 0, y: 0, coordinate: [10, 10] });
        await handleSurfaceClick({ x: 0, y: 0, coordinate: [20, 20] });
        resolveFirst({ ok: true, json: async () => ({
            lon: 10,
            lat: -10,
            observation_count: 1,
            spectra: {
                gpc1_mg_spectrum: [1],
                gpc2_al_spectrum: null,
                gpc3_un_spectrum: null,
                solar_mon_spectrum: null
            }
        }) });
        await first;

        expect(panel.innerHTML).toContain('No XRS observations');
    });

    it('shows an error message when the API responds with an error', async () => {
        stubBrowser(async () => ({ ok: false, status: 500 }));
        await handleSurfaceClick({ x: 0, y: 0, coordinate: [10, 10] });
        expect(panel.innerHTML).toContain('Error loading XRS data');
    });
});
