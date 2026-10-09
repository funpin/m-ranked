/**
 * Абстракция «поле рейтинга»: изометрическая сетка, на ней полупрозрачные
 * колонны вузов, в центре — три колонны знака m-ranked, средняя фирменного
 * синего цвета. Чистый SVG без запросов и скриптов: колонны один раз
 * вырастают при показе (CSS, конечная анимация), по верхним граням медленно
 * проходит блик (SMIL). При reduced motion блика нет, колонны стоят сразу.
 */

const COS = Math.cos(Math.PI / 6);
const SIN = 0.5;
const UNIT = 22;

function iso(x: number, y: number, z: number): [number, number] {
  return [(x - y) * COS * UNIT, (x + y) * SIN * UNIT - z * UNIT];
}

function points(list: [number, number, number][]) {
  return list.map(([x, y, z]) => iso(x, y, z).map((value) => value.toFixed(1)).join(",")).join(" ");
}

type Column = { x: number; y: number; h: number; tone: "brand" | "ink" | "soft" | "accent"; size?: number };

// Знак в центре и поле вокруг: высоты задают «рейтинг», без случайности —
// картинка одинакова при каждой отрисовке и не дёргает гидратацию.
const COLUMNS: Column[] = [
  { x: -1.2, y: 0, h: 4.2, tone: "ink", size: 0.9 },
  { x: 0, y: 0, h: 5.4, tone: "brand", size: 0.9 },
  { x: 1.2, y: 0, h: 3.4, tone: "ink", size: 0.9 },
  ...[
    [-4, -3, 1.4], [-2.5, -3.5, 2.2], [-1, -4, 1], [1.5, -3.5, 1.8], [3, -3, 2.6], [4.5, -2.5, 1.2],
    [-5, -1, 2], [-3.5, -1.5, 1.2], [3.5, -1, 1.6], [5, 0, 2.4], [-5, 1.5, 1.1], [-3.2, 2, 2.8],
    [3.2, 2, 1.4], [4.6, 2.6, 0.9], [-1.6, 3.4, 1.6], [0.6, 3.6, 2.1], [2.4, 3.8, 1.1], [-3.8, 4.2, 0.8],
  ].map(([x, y, h], index) => ({ x: x!, y: y!, h: h!, tone: index % 7 === 3 ? "accent" as const : "soft" as const, size: 0.62 })),
];

const FILL: Record<Column["tone"], { top: string; left: string; right: string; opacity: number }> = {
  brand: { top: "#5eb1ff", left: "#0074e4", right: "#0058b0", opacity: 1 },
  ink: { top: "var(--rank-ink-top)", left: "var(--rank-ink-left)", right: "var(--rank-ink-right)", opacity: 1 },
  soft: { top: "var(--rank-soft-top)", left: "var(--rank-soft-left)", right: "var(--rank-soft-right)", opacity: 0.9 },
  accent: { top: "#a68bff", left: "#7b5ce6", right: "#5f43c4", opacity: 0.85 },
};

function Prism({ column, index }: { column: Column; index: number }) {
  const s = column.size ?? 0.62;
  const { x, y, h } = column;
  const x0 = x - s / 2, x1 = x + s / 2, y0 = y - s / 2, y1 = y + s / 2;
  const fill = FILL[column.tone];
  // Колонна растёт от основания: transform-origin у нижней точки основания.
  const [bx, by] = iso(x1, y1, 0);
  return (
    <g className="rank-prism" style={{ transformOrigin: `${bx.toFixed(1)}px ${by.toFixed(1)}px`, animationDelay: `${(index % 9) * 70}ms` }} opacity={fill.opacity}>
      <polygon points={points([[x0, y1, 0], [x1, y1, 0], [x1, y1, h], [x0, y1, h]])} fill={fill.left} />
      <polygon points={points([[x1, y0, 0], [x1, y1, 0], [x1, y1, h], [x1, y0, h]])} fill={fill.right} />
      <polygon points={points([[x0, y0, h], [x1, y0, h], [x1, y1, h], [x0, y1, h]])} fill={fill.top} />
      {column.tone === "brand" || column.tone === "ink" ? (
        <polygon className="rank-sweep" points={points([[x0, y0, h], [x1, y0, h], [x1, y1, h], [x0, y1, h]])} fill="url(#rank-sweep)" />
      ) : null}
    </g>
  );
}

export function RankField({ className, label = "Абстракция: поле рейтинга вузов" }: { className?: string; label?: string }) {
  // Дальние колонны рисуются первыми, иначе ближние оказались бы под ними.
  const ordered = COLUMNS.map((column, index) => ({ column, index })).sort((a, b) => (a.column.x + a.column.y) - (b.column.x + b.column.y));
  const grid: string[] = [];
  for (let i = -6; i <= 6; i += 1) {
    const [ax, ay] = iso(i, -6, 0), [bx, by] = iso(i, 6, 0);
    const [cx, cy] = iso(-6, i, 0), [dx, dy] = iso(6, i, 0);
    grid.push(`M${ax.toFixed(1)} ${ay.toFixed(1)}L${bx.toFixed(1)} ${by.toFixed(1)}`, `M${cx.toFixed(1)} ${cy.toFixed(1)}L${dx.toFixed(1)} ${dy.toFixed(1)}`);
  }
  return (
    <svg viewBox="-190 -150 380 300" role="img" aria-label={label} className={`rank-field ${className ?? ""}`}>
      <defs>
        <radialGradient id="rank-glow" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#0082fe" stopOpacity="0.28" />
          <stop offset="0.6" stopColor="#7b5ce6" stopOpacity="0.08" />
          <stop offset="1" stopColor="#7b5ce6" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="rank-floor" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#fff" stopOpacity="1" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </radialGradient>
        <mask id="rank-floor-mask">
          <rect x="-190" y="-150" width="380" height="300" fill="url(#rank-floor)" />
        </mask>
        <linearGradient id="rank-sweep" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#fff" stopOpacity="0" />
          <stop offset="0.5" stopColor="#fff" stopOpacity="0.55">
            <animate attributeName="offset" values="-0.4;1.4" dur="6s" repeatCount="indefinite" />
          </stop>
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <ellipse cx="0" cy="10" rx="170" ry="110" fill="url(#rank-glow)" />
      <path d={grid.join("")} stroke="currentColor" strokeOpacity="0.14" strokeWidth="0.6" fill="none" mask="url(#rank-floor-mask)" />
      {ordered.map(({ column, index }) => <Prism key={index} column={column} index={index} />)}
    </svg>
  );
}
