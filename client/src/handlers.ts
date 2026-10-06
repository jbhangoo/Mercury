import { XRS_API_BASE } from './config.ts';
import { formatLongitude, toGeographicLatitude } from './coordinates.ts';
import type { XrsDetailPayload, DeckPickingInfo } from './types.ts';

function escapeHtml(value: string): string {
    return value.replace(/[&<>"']/g, character => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    })[character] ?? character);
}

export function handleSurfaceHover(coordinate: number[] | undefined): string {
    if (!coordinate) return '';

    const [lonEast, pickedLatitude] = coordinate;
    const lat = toGeographicLatitude(pickedLatitude);
    return `(${lat.toFixed(2)}, ${lonEast.toFixed(2)})`;
}

export async function handleSurfaceClick(info: DeckPickingInfo<unknown>): Promise<void> {
    if (!info.coordinate) return;

    // The rendered layers use FLIP_Y_MATRIX, so picked y has the opposite sign.
    const [lonEast, pickedLatitude] = info.coordinate;
    const lat = toGeographicLatitude(pickedLatitude);
    const longitudeLabel = formatLongitude(lonEast);
    const latitudeHemisphere = lat >= 0 ? 'N' : 'S';
    const latitudeLabel = `${Math.abs(lat).toFixed(2)}° ${latitudeHemisphere}`;

    const panel = document.getElementById('panel-content') as HTMLDivElement | null;
    if (!panel) return;

    panel.innerHTML = `<p>Loading XRS data for ${latitudeLabel}, ${longitudeLabel}...</p>`;

    try {
        const res = await fetch(`${XRS_API_BASE}/xrs?lon=${lonEast}&lat=${lat}`);

        if (!res.ok) {
            throw new Error(`Request failed: ${res.status}`);
        }

        const details: XrsDetailPayload = await res.json();
        const observations = details.observations.map(observation => `
            <article>
                <p><strong>MET:</strong> ${observation.met} · <strong>Orbit:</strong> ${observation.orbit_number}</p>
                <p><strong>Observed:</strong> ${escapeHtml(observation.observed_start)} –
                    ${escapeHtml(observation.observed_end)}</p>
                <p><strong>Solar flare detected:</strong> ${observation.solar_flare_detected ? 'Yes' : 'No'}</p>
                <p><strong>Solar intensity:</strong> ${
                    observation.solar_intensity === null
                        ? 'Unavailable'
                        : `${observation.solar_intensity}${observation.solar_intensity_source
                            ? ` (${escapeHtml(observation.solar_intensity_source)})`
                            : ''}`
                }</p>
                <details>
                    <summary>Detector spectra</summary>
                    <p>GPC1 Mg: ${observation.gpc1_mg_spectrum?.length ?? 0} channels</p>
                    <p>GPC2 Al: ${observation.gpc2_al_spectrum?.length ?? 0} channels</p>
                    <p>GPC3 Un: ${observation.gpc3_un_spectrum?.length ?? 0} channels</p>
                    <p>Solar monitor: ${observation.solar_mon_spectrum?.length ?? 0} channels</p>
                </details>
            </article>
        `).join('<hr style="border-color: #333;" />');

        panel.innerHTML = `
            <p><strong>Position:</strong> ${latitudeLabel}, ${longitudeLabel}</p>
            <hr style="border-color: #333;" />
            <p><strong>Matching observations:</strong> ${details.observations.length}</p>
            ${details.observations.length ? observations : '<p>No XRS observations have a footprint covering this position.</p>'}
            ${details.has_more ? '<p>Showing the first 100 observations.</p>' : ''}
        `;
    } catch (e) {
        panel.innerHTML = `<p style="color:red;">Error loading XRS data for this position.</p>`;
    }
}