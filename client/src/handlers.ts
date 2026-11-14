import { XRS_API_BASE } from './config.ts';
import { formatLatitude, formatLongitude, toGeographicLatitude } from './coordinates.ts';
import type { XrsSpectraPayload, DeckPickingInfo } from './types.ts';

function renderSpectrumSummary(spectra: XrsSpectraPayload['spectra']): string {
    return Object.entries(spectra).map(([name, values]) => {
        const total = values?.reduce<number | undefined>(
            (sum, value) => value === null ? sum : (sum ?? 0) + value,
            undefined
        );
        const formattedTotal = total === undefined ? 'Unavailable' : total.toFixed(2);
        return `<li><span class="label">${name}</span> ${formattedTotal} mean counts</li>`;
    }).join('');
}

export function handleSurfaceHover(coordinate: number[] | undefined): string {
    if (!coordinate) return '';

    const [lonEast, pickedLatitude] = coordinate;
    const lat = toGeographicLatitude(pickedLatitude);
    return `(${lat.toFixed(2)}, ${lonEast.toFixed(2)})`;
}

// Clicks can arrive faster than the server answers; only the latest one may update the sidebar.
let latestRequest = 0;

export async function handleSurfaceClick(info: DeckPickingInfo<unknown>): Promise<void> {
    if (!info.coordinate) return;

    // The rendered layers use FLIP_Y_MATRIX, so picked y has the opposite sign.
    const [lonEast, pickedLatitude] = info.coordinate;
    const lat = toGeographicLatitude(pickedLatitude);
    const positionLabel = `${formatLatitude(lat)}, ${formatLongitude(lonEast)}`;

    const panel = document.getElementById('panel-content') as HTMLDivElement | null;
    if (!panel) return;

    const request = ++latestRequest;
    panel.innerHTML = `<p>Loading XRS data for ${positionLabel}...</p>`;

    try {
        const res = await fetch(`${XRS_API_BASE}/xrs?lon=${lonEast}&lat=${lat}`);

        if (!res.ok) {
            throw new Error(`Request failed: ${res.status}`);
        }

        const details: XrsSpectraPayload = await res.json();
        if (request !== latestRequest) return;

        const count = details.observation_count;
        panel.innerHTML = `
            <p><strong>Position:</strong> ${positionLabel}</p>
            <p><strong>Matching observations:</strong> ${count}</p>
            ${count
                ? `<p>Spatially weighted mean spectra:</p><ul>${renderSpectrumSummary(details.spectra)}</ul>`
                : '<p>No XRS observations have a footprint covering this position.</p>'}
        `;
    } catch (e) {
        if (request !== latestRequest) return;
        panel.innerHTML = `<p style="color:red;">Error loading XRS data for this position.</p>`;
    }
}
