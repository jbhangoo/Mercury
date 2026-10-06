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
