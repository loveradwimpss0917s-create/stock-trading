import type { StrategyResult } from './api';

function fmt(v: number | null, digits = 2): string {
  return v === null || v === undefined ? '—' : v.toFixed(digits);
}

function pct(v: number | null): string {
  return v === null || v === undefined ? '—' : `${(v * 100).toFixed(1)}%`;
}

/** DSR is a probability against the selection benchmark; the blueprint's
 * gate is 0.95, so the bar is drawn against that rather than against 1.0. */
function DsrGauge({ dsr }: { dsr: number | null }) {
  if (dsr === null || dsr === undefined) return <span className="muted">—</span>;
  const tone = dsr > 0.95 ? 'ok' : dsr >= 0.9 ? 'warn' : 'bad';
  return (
    <div className="gauge">
      <div className="gauge-track">
        <div className={`gauge-fill gauge-${tone}`} style={{ width: `${Math.min(dsr, 1) * 100}%` }} />
        <div className="gauge-threshold" style={{ left: '95%' }} title="採用ゲート 0.95" />
      </div>
      <span className={`gauge-value tabular tone-${tone}`}>{dsr.toFixed(3)}</span>
    </div>
  );
}

export function StrategyPanel({
  strategies,
  passedCount,
}: {
  strategies: StrategyResult[];
  passedCount: number;
}) {
  if (strategies.length === 0) {
    return (
      <section className="panel">
        <h2>戦略の統計的検証</h2>
        <p className="muted">まだバックテストを実行していません。</p>
      </section>
    );
  }

  const pbo = strategies[0]?.pbo ?? null;
  const nTrials = strategies[0]?.n_trials ?? strategies.length;

  return (
    <section className="panel">
      <h2>戦略の統計的検証</h2>

      <div className={`verdict ${passedCount > 0 ? 'verdict-ok' : 'verdict-none'}`}>
        <span className="verdict-count tabular">{passedCount}</span>
        <span className="verdict-label">
          / {strategies.length} 戦略が採用ゲートを通過
        </span>
        <p className="verdict-note">
          ゲート: DSR &gt; 0.95 かつ PBO &lt; 0.5 かつ OOS Sharpe &gt; 0
          {passedCount === 0 && ' — 現時点で運用に足る戦略はありません。'}
        </p>
      </div>

      {pbo !== null && (
        <p className={`pbo-line ${pbo >= 0.5 ? 'tone-bad' : 'tone-ok'}`}>
          PBO {pbo.toFixed(3)}
          <span className="muted">
            {' '}
            — in-sampleで最良の戦略が、out-of-sampleで中央値以下に落ちる確率。
            {pbo >= 0.5
              ? 'コイン投げ以下で、この探索に情報がないことを示します。'
              : '0.5未満なので選択に情報があります。'}
            （{nTrials}戦略の探索全体に対する1つの値）
          </span>
        </p>
      )}

      <div className="table-scroll">
        <table className="quotes">
          <thead>
            <tr>
              <th>戦略</th>
              <th className="num">Sharpe(年率)</th>
              <th>DSR</th>
              <th className="num">最大DD</th>
              <th className="num">勝率</th>
              <th className="num">取引</th>
              <th className="num">歪度</th>
              <th className="num">尖度</th>
              <th>判定</th>
            </tr>
          </thead>
          <tbody>
            {strategies.map((s) => (
              <tr key={s.run_id}>
                <td>{s.strategy}</td>
                <td className={`num tabular ${(s.sharpe ?? 0) < 0 ? 'down' : 'up'}`}>
                  {fmt(s.sharpe, 3)}
                </td>
                <td>
                  <DsrGauge dsr={s.dsr} />
                </td>
                <td className="num tabular">{pct(s.max_dd)}</td>
                <td className="num tabular">{pct(s.win_rate)}</td>
                <td className="num tabular">{s.n_trades ?? '—'}</td>
                <td className="num tabular">{fmt(s.skew)}</td>
                <td className="num tabular">{fmt(s.kurtosis, 1)}</td>
                <td>
                  <span className={`pill ${s.passed ? 'pill-ok' : 'pill-bad'}`}>
                    {s.passed ? '合格' : '不合格'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="muted footnote">
        検証期間 {strategies[0]?.period_start} 〜 {strategies[0]?.period_end}。
        尖度が大きい戦略ほど、同じSharpeでも信頼できません（DSRはこれを補正済み）。
      </p>
    </section>
  );
}
