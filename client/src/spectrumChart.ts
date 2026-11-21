/**
 * Small line charts for the sidebar, drawn as inline SVG strings: no charting dependency, and the
 * functions are pure, so they can be tested without a browser.
 */
import type { SpectrumName } from './types.ts';

export interface SpectrumSeries {
    label: string;
    /** One value per channel; null channels leave a gap in the line. */
    values: Array<number | null>;
    /** Poisson error of each value (drawn as a +/- 1 sigma band), or null if not available. */
    errors: Array<number | null> | null;
    /** Instrument channel number of values[0]. */
    firstChannel: number;
}

/** First instrument channel of each spectrum array: GPC channels 10-253, solar monitor 23-253. */
export const FIRST_CHANNEL: Record<SpectrumName, number> = {
    gpc1_mg_spectrum: 10,
    gpc2_al_spectrum: 10,
    gpc3_un_spectrum: 10,
    solar_mon_spectrum: 23
};

const WIDTH = 308;   // the sidebar's content width; the SVG scales to its container
const HEIGHT = 150;
const MARGIN = { top: 8, right: 8, bottom: 28, left: 48 };
const LINE = '#64ffda';
const BAND = 'rgba(100, 255, 218, 0.22)';
const AXIS = '#45424e';
const TEXT = '#8892b0';

function escapeHtml(text: string): string {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function isFinite_(value: number | null | undefined): value is number {
    return typeof value === 'number' && Number.isFinite(value);
}

/** Short axis label: exponent form for very small or large values, two significant digits otherwise. */
export function formatTick(value: number): string {
    if (value === 0) return '0';
    const magnitude = Math.abs(value);
    if (magnitude < 0.01 || magnitude >= 10000) return value.toExponential(1);
    if (magnitude >= 100) return String(Math.round(value));
    return String(Number(value.toPrecision(2)));
}

/** Indices of the unbroken stretches of finite values, so missing channels leave gaps. */
function runsOfFiniteValues(values: Array<number | null>): number[][] {
    const runs: number[][] = [];
    let current: number[] = [];
    values.forEach((value, index) => {
        if (isFinite_(value)) {
            current.push(index);
        } else if (current.length) {
            runs.push(current);
            current = [];
        }
    });
    if (current.length) runs.push(current);
    return runs;
}

function channelTicks(first: number, last: number): number[] {
    const range = last - first;
    const step = range > 150 ? 50 : range > 60 ? 20 : 10;
    const ticks: number[] = [];
    for (let tick = Math.ceil(first / step) * step; tick <= last; tick += step) ticks.push(tick);
    return ticks;
}

function figure(label: string, body: string): string {
    return `<figure class="spectrum" style="margin:14px 0 0">`
        + `<figcaption style="color:${TEXT};font-size:0.85em;margin-bottom:2px">${escapeHtml(label)}</figcaption>`
        + `${body}</figure>`;
}

export function buildSpectrumChart(series: SpectrumSeries): string {
    const { label, values, errors, firstChannel } = series;

    const errorAt = (index: number): number => {
        const error = errors?.[index];
        return isFinite_(error) ? error : 0;
    };
    let yMax = 0;
    values.forEach((value, index) => {
        if (isFinite_(value)) yMax = Math.max(yMax, value + errorAt(index));
    });
    if (yMax <= 0) {
        return figure(label, `<p class="hint" style="margin:0">No data for this spectrum.</p>`);
    }

    const plotWidth = WIDTH - MARGIN.left - MARGIN.right;
    const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
    const lastChannel = firstChannel + values.length - 1;
    const x = (index: number): number =>
        MARGIN.left + (values.length > 1 ? (index / (values.length - 1)) * plotWidth : plotWidth / 2);
    const y = (value: number): number => MARGIN.top + plotHeight * (1 - value / yMax);
    const point = (index: number, value: number): string => `${x(index).toFixed(1)},${y(value).toFixed(1)}`;

    const parts: string[] = [];

    // Gridlines and y axis labels at 0, half and full scale.
    for (const fraction of [0, 0.5, 1]) {
        const value = yMax * fraction;
        const yy = y(value).toFixed(1);
        parts.push(
            `<line x1="${MARGIN.left}" x2="${WIDTH - MARGIN.right}" y1="${yy}" y2="${yy}" stroke="${AXIS}" stroke-width="${fraction === 0 ? 1 : 0.5}"/>`,
            `<text x="${MARGIN.left - 5}" y="${yy}" fill="${TEXT}" font-size="10" text-anchor="end" dominant-baseline="middle">${formatTick(value)}</text>`
        );
    }

    // x axis ticks at round channel numbers.
    const channelToX = (channel: number): number => x(channel - firstChannel);
    for (const channel of channelTicks(firstChannel, lastChannel)) {
        const xx = channelToX(channel).toFixed(1);
        parts.push(
            `<line x1="${xx}" x2="${xx}" y1="${y(0).toFixed(1)}" y2="${(y(0) + 4).toFixed(1)}" stroke="${AXIS}"/>`,
            `<text x="${xx}" y="${(y(0) + 15).toFixed(1)}" fill="${TEXT}" font-size="10" text-anchor="middle">${channel}</text>`
        );
    }
    parts.push(
        `<text x="${MARGIN.left + plotWidth / 2}" y="${HEIGHT - 3}" fill="${TEXT}" font-size="10" text-anchor="middle">channel</text>`
    );

    // One line (and error band) per unbroken run of channels.
    for (const run of runsOfFiniteValues(values)) {
        const bandable = run.length > 1 && run.every((index) => isFinite_(errors?.[index]));
        if (bandable) {
            const upper = run.map((index) => point(index, (values[index] as number) + errorAt(index)));
            const lower = run.map((index) => point(index, Math.max(0, (values[index] as number) - errorAt(index)))).reverse();
            parts.push(`<polygon points="${[...upper, ...lower].join(' ')}" fill="${BAND}" stroke="none"/>`);
        }
        const path = run.map((index, position) => `${position === 0 ? 'M' : 'L'}${point(index, values[index] as number)}`).join(' ');
        // A one-channel run is drawn as a dot (zero-length segment with round caps).
        parts.push(`<path d="${path}${run.length === 1 ? ' l0,0' : ''}" fill="none" stroke="${LINE}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>`);
    }

    const svg = `<svg viewBox="0 0 ${WIDTH} ${HEIGHT}" width="100%" role="img" `
        + `aria-label="${escapeHtml(label)}, channels ${firstChannel} to ${lastChannel}" `
        + `xmlns="http://www.w3.org/2000/svg">${parts.join('')}</svg>`;
    return figure(label, svg);
}