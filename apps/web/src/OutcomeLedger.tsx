import { useEffect, useMemo, useState } from 'react';
import {
  fetchOutcomes,
  fetchThemes,
  type Outcome,
  type OutcomeTotals,
  type Theme,
} from './api';

const HORIZON_LABEL: Record<string, string> = { day: 'デイ', swing: 'スイング' };

const OUTCOME_LABEL: Record<string, { text: string; cls: string }> = {
  target: { text: '目標到達', cls: 'up' },
  stop: { text: '損切り', cls: 'down' },
  timeout: { text: '期限切れ', cls: '' },
  no_entry: { text: '見送り', cls: 'muted' },
};

function yen(v: number | null | undefined): string {
  if (v == null) return '—';
  const n = Math.round(v);
  return `${n > 0 ? '+' : ''}${n.toLocaleString('ja-JP')}`;
}

/** Same sizing rule the candidates tab uses, so the yen figure here is what
 * that screen would have had you trade — not a different book. */
function shares(capital: number, riskPct: number, entry: number, stop: number): number {
  const risk = entry - stop;
  if (risk <= 0) return 0;
  return Math.max(0, Math.floor(Math.floor((capital * riskPct) / risk) / 100) * 100);
}

export function OutcomeLedger() {
  const [rows, setRows] = useState<Outcome[]>([]);
  const [totals, setTotals] = useState<OutcomeTotals[]>([]);
  const [themes, setThemes] = useState<Theme[]>([]);
  const [horizon, setHorizon] = useState<'day' | 'swing'>('swing');
  const [themeKey, setThemeKey] = useState('');
  const [capital, setCapital] = useState(1_000_000);
  const [riskPct, setRiskPct] = useState(0.01);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchThemes()
      .then((r) => setThemes(r.themes))
      .catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    fetchOutcomes({ horizon, theme: themeKey || undefined, limit: 300 })
      .then((r) => {
        setRows(r.outcomes);
        setTotals(r.totals);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [horizon, themeKey]);

  const visibleThemes = useMemo(
    () => themes.filter((t) => t.horizon === horizon || t.horizon === 'both'),
    [themes, horizon]
  );

  const total = totals.find((t) => t.horizon === horizon);

  // Yen totals are computed over the rows on screen, not over the whole
  // history, because sizing depends on the capital entered here and the API
  // returns the most recent 300 trades rather than all 16,000.
  const shown = useMemo(() => {
    let pnl = 0;
    let n = 0;
    let wins = 0;
    for (const r of rows) {
      if (r.outcome === 'no_entry' || r.entry_fill == null || r.exit_price == null) continue;
      const qty = shares(capital, riskPct, r.entry_fill, r.stop_price ?? 0);
      pnl += qty * (r.exit_price - r.entry_fill);
      n += 1;
      if ((r.r_multiple ?? 0) > 0) wins += 1;
    }
    return { pnl, n, wins };
  }, [rows, capital, riskPct]);

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>銘柄別の結果</h2>
        <div className="seg">
          {(['swing', 'day'] as const).map((h) => (
            <button
              key={h}
              className={`seg-btn${horizon === h ? ' is-active' : ''}`}
              onClick={() => {
                setHorizon(h);
                setThemeKey('');
              }}
            >
              {HORIZON_LABEL[h]}
            </button>
          ))}
        </div>
      </div>

      <div className="filters">
        <select
          className="select"
          value={themeKey}
          onChange={(e) => setThemeKey(e.target.value)}
          aria-label="テーマ"
        >
          <option value="">全テーマ</option>
          {visibleThemes.map((t) => (
            <option key={t.key} value={t.key}>
              {t.name_ja}
            </option>
          ))}
        </select>
        <label className="field">
          資金
          <input
            type="number"
            className="num-input tabular"
            value={capital}
            step={100000}
            min={0}
            onChange={(e) => setCapital(Number(e.target.value))}
          />
        </label>
        <label className="field">
          1回の許容損失
          <select
            className="select"
            value={riskPct}
            onChange={(e) => setRiskPct(Number(e.target.value))}
          >
            <option value={0.005}>0.5%</option>
            <option value={0.01}>1%</option>
            <option value={0.02}>2%</option>
          </select>
        </label>
      </div>

      {error && <p className="status-error">エラー: {error}</p>}
      {loading && <p className="muted">読み込み中…</p>}

      {!loading && rows.length > 0 && (
        <>
          <div className={`verdict ${shown.pnl >= 0 ? 'verdict-ok' : 'verdict-none'}`}>
            <span className="verdict-count tabular">{yen(shown.pnl)}円</span>
            <span className="verdict-label">
              直近{shown.n.toLocaleString('ja-JP')}件を<strong>すべて</strong>この資金・リスク設定で
              取っていた場合の合計（勝ち {shown.wins}件 / 負け {shown.n - shown.wins}件）
            </span>
            <p className="verdict-note">
              1銘柄ずつ同じ株数計算（損切りで資金の{(riskPct * 100).toFixed(1)}%を失う逆算、100株単位）で
              建てた前提です。<strong>手数料と税金は含みません。</strong>
              同時に何銘柄も持つ資金繰りは考慮していないので、
              「1件あたりの損益の合計」であって実際の口座残高の推移ではありません。
              {total && (
                <>
                  {' '}
                  全期間では{total.n_trades.toLocaleString('ja-JP')}件・合計
                  {total.total_r?.toFixed(1)}R（平均{total.avg_r?.toFixed(3)}R、
                  平均保有{total.avg_bars_held}営業日）。
                </>
              )}
            </p>
          </div>

          <div className="table-scroll">
            <table className="quotes">
              <thead>
                <tr>
                  <th>基準日</th>
                  <th>銘柄</th>
                  <th>テーマ</th>
                  <th className="num">約定</th>
                  <th className="num">決済</th>
                  <th>結果</th>
                  <th className="num">保有</th>
                  <th className="num">株数</th>
                  <th className="num">損益(円)</th>
                  <th className="num">R</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const label = OUTCOME_LABEL[r.outcome] ?? { text: r.outcome, cls: '' };
                  const qty =
                    r.entry_fill == null
                      ? 0
                      : shares(capital, riskPct, r.entry_fill, r.stop_price ?? 0);
                  const pnl =
                    r.entry_fill != null && r.exit_price != null
                      ? qty * (r.exit_price - r.entry_fill)
                      : null;
                  return (
                    <tr key={`${r.as_of}/${r.theme_key}/${r.code}`}>
                      <td className="tabular">{r.as_of}</td>
                      <td>
                        <span className="tabular code">{r.ticker4}</span> {r.name_ja}
                      </td>
                      <td className="muted">{r.theme_name}</td>
                      <td className="num tabular">
                        {r.entry_fill?.toLocaleString('ja-JP') ?? '—'}
                      </td>
                      <td className="num tabular">
                        {r.exit_price?.toLocaleString('ja-JP') ?? '—'}
                      </td>
                      <td className={label.cls}>{label.text}</td>
                      <td className="num tabular">{r.bars_held || '—'}</td>
                      <td className="num tabular">{qty ? qty.toLocaleString('ja-JP') : '—'}</td>
                      <td className={`num tabular ${(pnl ?? 0) >= 0 ? 'up' : 'down'}`}>
                        {pnl == null ? '—' : yen(pnl)}
                      </td>
                      <td className={`num tabular ${(r.r_multiple ?? 0) >= 0 ? 'up' : 'down'}`}>
                        {r.r_multiple == null ? '—' : r.r_multiple.toFixed(2)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <p className="muted footnote">
            新しい順に最大300件を表示しています。
            <strong>「売買候補」タブに今出ている銘柄はここにまだ出ません。</strong>
            結果を出すには約定日以降の値動きが必要で、スイングなら基準日の10営業日後まで
            データが揃って初めて判定できるためです。
            現在判定済みなのは {total?.last_as_of ?? '—'} 分までです。
          </p>
        </>
      )}
    </section>
  );
}
