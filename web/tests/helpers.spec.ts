import { test, expect } from '@playwright/test';
import { excerpt, highlightParts, sourceParts } from '../src/helpers';
import type { Chunk } from '../src/types';

function chunk(text: string, start_offset: number, end_offset: number): Chunk {
  return { id: 'synthetic-chunk', text, start_offset, end_offset, page: null, ordinal: 0 };
}

test('pure citation helper: exact Unicode codepoint spans only; unsafe or mismatched offsets fall back', () => {
  const content = '😀 앞부분 👩‍💻 근거 é 끝';
  const match = '👩‍💻 근거 é';
  const start = Array.from(content.slice(0, content.indexOf(match))).length;
  const end = start + Array.from(match).length;
  expect(sourceParts(content, chunk(match, start, end))).toEqual({ before: '😀 앞부분 ', match, after: ' 끝' });
  expect(sourceParts(content)).toBeNull();
  expect(sourceParts(content, chunk('incorrect text', start, end))).toBeNull();
  expect(sourceParts(content, chunk(match, content.indexOf(match), content.indexOf(match) + match.length))).toBeNull();
  for (const [from, to] of [[-1, end], [start, 999], [end, start], [start, start], [0.5, end], [start, NaN]]) {
    expect(sourceParts(content, chunk(match, from, to))).toBeNull();
  }
});

test('pure highlight helper: regex metacharacters are literal and HTML text is preserved', () => {
  const text = '<img src=x onerror="synthetic()"> [a+b] a.b aXb (test) $5 \\path 😀';
  const parts = highlightParts(text, '[a+b] a.b (test) $5 \\path 😀');
  expect(parts.map(part => part.text).join('')).toBe(text);
  expect(parts.filter(part => part.marked).map(part => part.text)).toEqual(['[a+b]', 'a.b', '(test)', '$5', '\\path', '😀']);
  expect(highlightParts(text, '   ')).toEqual([{ text, marked: false }]);
  expect(highlightParts('Alpha ALPHA alpha', 'alpha').filter(part => part.marked)).toHaveLength(3);
});

test('pure excerpt helper: emoji remain whole at both excerpt boundaries', () => {
  // The initial start/end fall on low surrogates at UTF-16 positions 61/321.
  const content = `${'a'.repeat(60)}😀${'b'.repeat(39)}marker${'c'.repeat(213)}😀${'z'.repeat(100)}`;
  const result = excerpt(content, 'marker');
  expect(result).toContain('marker');
  expect(result.startsWith('…😀')).toBe(true);
  expect(result.endsWith('😀…')).toBe(true);
  expect(Array.from(result).filter(point => point.length === 1 && /[\uD800-\uDFFF]/.test(point))).toEqual([]);
});
