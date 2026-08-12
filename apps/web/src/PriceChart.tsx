import type { DailyQuote } from './api';

const WIDTH = 720;
const HEIGHT = 260;
const PAD = { top: 12, right: 56, bottom: 24, left: 8 };

/** Inline SVG close-price line. Deliberately dependency-free: the design
 * blueprint suggests lightweight-charts, but a single line series doesn't
 * justify the bundle yet — swap it in when candlesticks/overlays land. */
export function PriceChart({ quotes }: { quotes: DailyQuote[] }) {
  const points = quotes
    .map((q) => ({ date: q.date, close: q.close === null ? NaN : Number(q.close) }))
    .filter((p) => !Number.isNaN(p.close));

  if (points.length < 2) {
    return <p className="muted">価格データが不足しています。</p>;
  }

  const closes = points.map((p) => p.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = max - min || 1;

  const plotW = WIDTH - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;

  const x = (i: number) => PAD.left + (i / (points.length - 1)) * plotW;
  const y = (v: number) => PAD.top + (1 - (v - min) / span) * plotH;

  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.close).toFixed(1)}`).join(' ');
  const area = `${path} L${x(points.length - 1).toFixed(1)},${PAD.top + plotH} L${x(0).toFixed(1)},${PAD.top + plotH} Z`;

  const first = points[0]!;
  const last = points[points.length - 1]!;
  const up = last.close >= first.close;
  const stroke = up ? 'var(--up)' : 'var(--down)';

  const gridValues = [max, min + span / 2, min];

  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="終値の推移">
        {gridValues.map((v) => (
          <g key={v}>
            <line x1={PAD.left} x2={PAD.left + plotW} y1={y(v)} y2={y(v)} className="grid" />
            <text x={PAD.left + plotW + 8} y={y(v) + 4} className="axis tabular">
              {v.toLocaleString('ja-JP', { maximumFractionDigits: 0 })}
            </text>
          </g>
        ))}

        <path d={area} fill={stroke} opacity="0.08" />
        <path d={path} fill="none" stroke={stroke} strokeWidth="1.75" />

        <text x={PAD.left} y={HEIGHT - 6} className="axis">
          {first.date}
        </text>
        <text x={PAD.left + plotW} y={HEIGHT - 6} textAnchor="end" className="axis">
          {last.date}
        </text>
      </svg>
    </figure>
  );
}
