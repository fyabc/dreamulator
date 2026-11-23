const paths = {
  arrow: 'M4 12h15m-6-6 6 6-6 6',
  back: 'M20 12H5m6 6-6-6 6-6',
  undo: 'M9 4 4 9l5 5M4 9h10a6 6 0 0 1 0 12h-3',
  lock: 'M5 11h14v10H5zM8 11V7a4 4 0 1 1 8 0v4m-4 4v2',
  unlock: 'M5 11h14v10H5zM8 11V7a4 4 0 0 1 7.5-2M12 15v2',
  close: 'm6 6 12 12M18 6 6 18',
  home: 'm3 10 9-7 9 7v10h-6v-6H9v6H3z',
  globe: 'M2 12a10 10 0 1 0 20 0 10 10 0 1 0-20 0m0 0h20M12 2a17 17 0 0 0 0 20m0-20a17 17 0 0 1 0 20',
  import: 'M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5',
  frame: 'M9 4H4v5m11-5h5v5M4 15v5h5m11-5v5h-5M12 9v6m-3-3h6',
  flag: 'M5 21V4m0 1c5-4 9 4 14 0v10c-5 4-9-4-14 0',
  flask: 'M9 3h6m-5 0v7l-5 8a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-8V3M8 15h8',
  help: 'M2 12a10 10 0 1 0 20 0 10 10 0 1 0-20 0m7-3a3 3 0 1 1 4 3c-1 .5-1 1-1 2m0 3h.01',
  folder: 'M3 6h7l2 2h9v12H3z',
  overview: 'M5 3h14v18H5zM9 8h6m-6 4h6m-6 4h4',
  orbit: 'M5 12a7 7 0 1 0 14 0 7 7 0 1 0-14 0m5 0h4m-2-2v4M3 17c-2-2 1-6 6-9s10-4 12-2-1 6-6 9-10 4-12 2Z',
  system: 'M3 12h5m8 0h5M12 3v5m0 8v5m-6.4-2.6 3.6-3.6m5.6-5.6 3.6-3.6M5.6 5.6l3.6 3.6m5.6 5.6 3.6 3.6M9 12a3 3 0 1 0 6 0 3 3 0 0 0-6 0Z',
  stars: 'm11 3 2 6 6 2-6 2-2 6-2-6-6-2 6-2 2-6Zm8 12v5m-2.5-2.5h5',
  menu: 'M4 6h16M4 12h16M4 18h16',
  layers: 'm3 8 9-5 9 5-9 5-9-5Zm0 5 9 5 9-5M3 18l9 5 9-5',
  geology: 'M3 19h18L14 6l-4 7-2-3-5 9Zm8-7 3 2 2-3',
  compass: 'M2 12a10 10 0 1 0 20 0 10 10 0 1 0-20 0m6 4 2-6 6-2-2 6-6 2Z',
  climate: 'M5 15a3 3 0 1 1 .6-5.9 5 5 0 0 1 9.8 0A3 3 0 1 1 17 15H5Zm3 3-1 3m5-3-1 3m5-3-1 3',
  chart: 'M3 4v16h18M8 16v-4m5 4V8m5 8V5',
  leaf: 'M20 4c-6 0-13 2-13 8a5 5 0 0 0 5 5c6 0 8-7 8-13ZM4 20l10-10',
  temple: 'M3 9h18L12 3 3 9Zm2 12h14M7 12v6m5-6v6m5-6v6',
  more: 'M5 12h.01m6.99 0h.01m6.99 0h.01',
  pause: 'M9 5v14m6-14v14',
  play: 'm9 5 11 7-11 7z',
  spin: 'M12 6.5a6 6 0 1 0 0 12 6 6 0 0 0 0-12M12 1.5v3M12 20v3M6 12.5a6 3 0 0 0 12 0M18 12.5l-2.3 1.8M18 12.5l1.8 2.3',
} as const

export type AtlasIconName = keyof typeof paths

export default function AtlasIcon({ name, className = 'size-5' }: { name: AtlasIconName; className?: string }) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth={name === 'more' ? 3 : 1.6} strokeLinecap="round" strokeLinejoin="round"
    className={`shrink-0 ${className}`}><path d={paths[name]} /></svg>
}
