import type { ReactNode } from 'react';

const icons: Record<string, ReactNode> = {
  logo: <><path d="M5 3h9l5 5v13H5z"/><path d="M14 3v6h5M9 13h6M9 17h4"/></>,
  search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/></>,
  book: <path d="M4 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-4-3H4zM13 7a3 3 0 0 1 3-3h4v14h-3a4 4 0 0 0-4 3"/>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  plus: <path d="M12 5v14M5 12h14"/>, upload: <path d="M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5"/>,
  arrow: <path d="M5 12h14m-5-5 5 5-5 5"/>, close: <path d="m6 6 12 12M6 18 18 6"/>, check: <path d="m5 12 4 4L19 6"/>,
  file: <path d="M6 3h8l5 5v13H6zM14 3v6h5M10 13h5M10 17h5"/>,
  lock: <><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></>,
  people: <><circle cx="9" cy="8" r="3"/><path d="M3 20v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6m2 3a5 5 0 0 1 3 4v2"/></>,
  exit: <path d="M10 4H4v16h6m4-12 4 4-4 4M8 12h12"/>, edit: <path d="m15 4 5 5M4 20l5-1L21 7l-5-5L4 14z"/>,
  chevron: <path d="m8 5 7 7-7 7"/>, quote: <path d="M5 11h5v7H3v-7c0-4 2-6 6-6M16 11h5v7h-7v-7c0-4 2-6 6-6"/>,
};
export function Icon({ name, className = '' }: { name: string; className?: string }) {
  return <svg className={`icon ${className}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{icons[name] || icons.file}</svg>;
}
export function Brand() { return <a className="brand" href="/"><Icon name="logo"/><span>DocTrail</span></a>; }
