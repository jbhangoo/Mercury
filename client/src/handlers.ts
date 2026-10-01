import { XRS_API_BASE } from './config.ts';
import { formatLongitude, toGeographicLatitude } from './coordinates.ts';
import type { XrsDetailPayload, DeckPickingInfo } from './types.ts';

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

        panel.innerHTML = `
            <p><strong>Position:</strong> ${latitudeLabel}, ${longitudeLabel}</p>
            <hr style="border-color: #333;" />
            <p>Integrated Value: <span class="metric-value">${details.aggregatedValue}</span></p>
            <p>Solar Intensity: <strong>${details.solarIntensity}</strong></p>
            <p>Composition: <strong>${details.composition}</strong></p>
        `;
    } catch (e) {
        panel.innerHTML = `<p style="color:red;">Error loading XRS data for this position.</p>`;
    }
}