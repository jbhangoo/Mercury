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

    it('requests XRS data with geographic lat/lon and renders the result', async () => {
        const payload = {
            lon: -80.5,
            lat: 30,
            has_more: false,
            observations: [{
                id: 1,
                source_file: 'xrscdr2013101.dat',
                met: 123456,
                orbit_number: 25,
                observed_start: '2013-04-11T04:00:00+00:00',
                observed_end: '2013-04-11T04:05:00+00:00',
                fov_status: 1,
                intersection: true,
                data_quality: 0,
                center_lon: -80.5,
                center_lat: 30,
                spacecraft_altitude_km: 400,
                solar_flare_detected: true,
                solar_monitor_rate: null,
                solar_monitor_spect_shift: null,
                solar_intensity: null,
                solar_intensity_source: null,
                gpc1_mg_spectrum: [1, 2],
                gpc2_al_spectrum: [3, 4],
                gpc3_un_spectrum: [5, 6],
                solar_mon_spectrum: [7, 8],
                housekeeping: {}
            }]
        };
        const fetchMock = stubBrowser(async () => ({ ok: true, json: async () => payload }));

        await handleSurfaceClick({ x: 0, y: 0, coordinate: [-80.5, -30] });

        expect(fetchMock).toHaveBeenCalledWith(`${XRS_API_BASE}/xrs?lon=-80.5&lat=30`);
        expect(panel.innerHTML).toContain('30.00° N, 80.50° W');
        expect(panel.innerHTML).toContain('123456');
        expect(panel.innerHTML).not.toContain('Composition');
    });

    it('explains when no observation footprint covers the selected position', async () => {
        stubBrowser(async () => ({
            ok: true,
            json: async () => ({ lon: 10, lat: 10, observations: [], has_more: false })
        }));

        await handleSurfaceClick({ x: 0, y: 0, coordinate: [10, 10] });

        expect(panel.innerHTML).toContain('No XRS observations have a footprint covering this position.');
    });

    it('shows an error message when the API responds with an error', async () => {
        stubBrowser(async () => ({ ok: false, status: 500 }));
        await handleSurfaceClick({ x: 0, y: 0, coordinate: [10, 10] });
        expect(panel.innerHTML).toContain('Error loading XRS data');
    });
});
