const paths = {
  grid: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
  request: "M6 3h9l3 3v15H6zM9 9h6M9 13h6M9 17h4",
  plus: "M12 5v14M5 12h14",
  feed: "M4 6h16M4 12h16M4 18h10",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 3",
  upload: "M12 16V4M7 9l5-5 5 5M5 20h14",
  statement: "M7 3h10v18H7zM10 8h4M10 12h4M10 16h2",
  account: "M4 6h16v12H4zM4 10h16M8 15h3",
  people: "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM3 19c0-3 3-5 6-5s6 2 6 5M16 5a3 3 0 0 1 0 6M18 14c2 1 3 3 3 5",
  certificate: "M6 3h12v14H6zM9 7h6M9 11h6M10 17v4l2-1 2 1v-4",
  invoice: "M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6",
  card: "M3 6h18v12H3zM3 10h18M7 15h4",
  tender: "M4 10l8-6 8 6M6 10v8M10 10v8M14 10v8M18 10v8M4 20h16",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19 12l2-1-1-3-2 .5-1.5-1.5.5-2-3-1-1 2h-2l-1-2-3 1 .5 2L6 7.5 4 7 3 10l2 2-2 2 1 3 2-.5 1.5 1.5-.5 2 3 1 1-2h2l1 2 3-1-.5-2 1.5-1.5 2 .5 1-3z",
  mail: "M3 6h18v12H3zM3 7l9 6 9-6",
  bell: "M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 20h4",
  insight: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z",
  chevron: "M9 6l6 6-6 6",
  download: "M12 4v12M7 11l5 5 5-5M5 20h14",
} as const;

export type IconName = keyof typeof paths;

export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={paths[name]} />
    </svg>
  );
}
