import { XRS_API_BASE } from './config.ts';
import { formatLatitude, formatLongitude, toGeographicLatitude } from './coordinates.ts';
import { buildSpectrumChart, FIRST_CHANNEL } from './spectrumChart.ts';
import type { SpectrumName, XrsSpectraPayload, DeckPickingInfo } from './types.ts';

function renderSpectra(details: XrsSpectraPayload): string {
    const used = details.observations_used ?? details.observation_count;
    if (used === 0) {
        return `<p class="hint">None of the ${details.observation_count} overlapping observations has a usable `
            + `solar monitor rate, so no spectrum can be integrated here.</p>`;
    }
    const charts = (Object.keys(details.spectra) as SpectrumName[]).map((name) => buildSpectrumChart({
        label: name,
        values: details.spectra[name] ?? [],
        errors: details.spectra_error?.[name] ?? null,
        firstChannel: FIRST_CHANNEL[name]
    })).join('');
    const units = details.units ? `<p class="hint">${details.units} (shaded: ±1 σ)</p>` : '';
    const skipped = used < details.observation_count
        ? `<p class="hint">${details.observation_count - used} of ${details.observation_count} observations `
            + `had no usable solar monitor rate and are not included.</p>`
        : '';
    return `<p>Integrated spectra (${used} observation${used === 1 ? '' : 's'}):</p>${units}${skipped}${charts}`;
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
                ? renderSpectra(details)
                : '<p>No XRS observations have a footprint covering this position.</p>'}
        `;
    } catch (e) {
        if (request !== latestRequest) return;
        panel.innerHTML = `<p style="color:red;">Error loading XRS data for this position.</p>`;
    }
}