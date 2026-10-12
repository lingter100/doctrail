import type { Chunk, Doc } from './types';

export const date = (value: string) => new Intl.DateTimeFormat('ko-KR', { month: 'short', day: 'numeric' }).format(new Date(value));
export const fullDate = (value: string) => new Date(value).toLocaleString('ko-KR');
export const statusLabel = (doc: Doc) => doc.status === 'ready' ? '검색 가능' : doc.status === 'failed' ? '처리 실패' : '처리 중';
export const visibilityLabel = (doc: Doc) => doc.visibility === 'private' ? '나만 보기' : '워크스페이스';

export function excerpt(text: string, query: string): string {
  const terms = [...new Set(query.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean))];
  const paragraphs = [...text.matchAll(/[^\n]+(?:\n(?!\s*\n)[^\n]+)*/g)];
  const ranked = paragraphs.map(paragraph => {
    const lower = paragraph[0].toLocaleLowerCase();
    const matching = terms.filter(term => lower.includes(term));
    const count = matching.reduce((total, term) => total + lower.split(term).length - 1, 0);
    const score = matching.length * 10 + Math.min(count, 8) + Math.min(paragraph[0].length / 100, 2) - (/^\s*#{1,6}\s/.test(paragraph[0]) ? 8 : 0);
    return { paragraph, matching, lower, score: matching.length ? score : -1 };
  }).sort((a, b) => b.score - a.score);
  const best = ranked[0];
  const matchOffset = best?.matching.length ? Math.min(...best.matching.map(term => best.lower.indexOf(term))) + best.paragraph.index! : 0;
  let start = Math.max(0, matchOffset - 40);
  let end = Math.min(text.length, start + 260);
  if (start > 0 && /[\uDC00-\uDFFF]/.test(text[start])) start--;
  if (end < text.length && /[\uDC00-\uDFFF]/.test(text[end])) end++;
  return `${start ? '…' : ''}${text.slice(start, end)}${end < text.length ? '…' : ''}`;
}

export function highlightParts(text: string, query: string): { text: string; marked: boolean }[] {
  const terms = [...new Set(query.trim().split(/\s+/).filter(Boolean))].sort((a, b) => b.length - a.length);
  if (!terms.length) return [{ text, marked: false }];
  const regex = new RegExp(terms.map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'giu');
  const parts: { text: string; marked: boolean }[] = [];
  let last = 0;
  for (const match of text.matchAll(regex)) {
    parts.push({ text: text.slice(last, match.index), marked: false }, { text: match[0], marked: true });
    last = match.index! + match[0].length;
  }
  parts.push({ text: text.slice(last), marked: false });
  return parts;
}

export function sourceParts(content: string, citation?: Chunk): { before: string; match: string; after: string } | null {
  if (!citation) return null;
  // Both services expose Unicode codepoint offsets, not JavaScript UTF-16 units.
  const points = Array.from(content);
  const { start_offset: start, end_offset: end } = citation;
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end > points.length) return null;
  const match = points.slice(start, end).join('');
  if (match !== citation.text) return null;
  return { before: points.slice(0, start).join(''), match, after: points.slice(end).join('') };
}
