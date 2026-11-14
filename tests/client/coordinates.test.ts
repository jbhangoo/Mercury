import { describe, expect, it } from 'vitest';
import { formatLongitude, toGeographicLatitude } from '../../client/src/coordinates.ts';

describe('coordinate conversions', () => {
    it('flips picked latitude to geographic latitude', () => {
        expect(toGeographicLatitude(-30)).toBe(30);
    });

    it('formats longitude with its east or west hemisphere', () => {
        expect(formatLongitude(80.5)).toBe('80.50° E');
        expect(formatLongitude(-80.5)).toBe('80.50° W');
        expect(formatLongitude(0)).toBe('0.00° E');
    });
});

import { formatLatitude } from '../../client/src/coordinates.ts';

describe('formatLatitude', () => {
    it('adds the hemisphere letter', () => {
        expect(formatLatitude(30.254)).toBe('30.25° N');
        expect(formatLatitude(-74.875)).toBe('74.88° S');
    });
});
