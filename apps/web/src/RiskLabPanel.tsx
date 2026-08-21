import { useMemo, useState } from 'react';
import { expectancyR, kellyFraction, requiredWinRate, simulate } from './lib/ruin';

const RISK_LADDER = [0.005, 0.01, 0.02, 0.03, 0.05, 0.1];

function pct(v: number, digits = 1): string {
  return `${(v * 100).toFixed(digits)}%`;
}

export function RiskLabPanel() {
  const [winRate, setWinRate] = useState(0.5);
  const [rr, setRr] = useState(1.5);
  const [riskPerTrade, setRiskPerTrade] = useState(0.01);
  const [nTrades, setNTrades] = useState(200);
  const [capital, setCapital] = useState(5_000_000);

  const exp = expectancyR(winRate, rr, 1);
  const needed = requiredWinRate(rr, 1);
  const kelly = kellyFraction(winRate, rr, 1);

  const result = useMemo(
    () => simulate({ winRate, avgWinR: rr, avgLossR: 1, riskPerTrade, nTrades }),
    [winRate, rr, riskPerTrade, nTrades]
  );

  const ladder = useMemo(
    () =>
      RISK_LADDER.map((risk) => ({
        risk,
        ...simulate({ winRate, avgWinR: rr, avgLossR: 1, riskPerTrade: risk, nTrades }),
      })),
    [winRate, rr, nTrades]
  );

  const edgeOk = exp > 0;

  return (
    <section className="panel">
      <h2>リスク計算</h2>
      <p className="muted footnote">
        <strong>ここだけは、優位性の有無と無関係に今日から正しく動きます。</strong>
        勝率・R:R・1回のリスクを決めれば、破産確率もドローダウンも予測ではなく算術で出ます。
        銘柄選択に価値が見つからなくても、この部分の価値は変わりません。
      </p>

      <div className="filters">
        <label className="field">
          勝率
          <input
            type="range"
            min={20}
            max={80}
            step={0.5}
            value={winRate * 100}
            onChange={(e) => setWinRate(Number(e.target.value) / 100)}
          />
          <span className="tabular">{pct(winRate)}</span>
        </label>
        <label className="field">
          R:R（利益÷損失）
          <input
            type="range"
            min={0.5}
            max={4}
            step={0.05}
            value={rr}
            onChange={(e) => setRr(Number(e.target.value))}
          />
          <span className="tabular">{rr.toFixed(2)}</span>
        </label>
        <label className="field">
          1回のリスク
          <input
            type="range"
            min={0.1}
            max={10}
            step={0.1}
            value={riskPerTrade * 100}
            onChange={(e) => setRiskPerTrade(Number(e.target.value) / 100)}
          />
          <span className="tabular">{pct(riskPerTrade)}</span>
        </label>
        <label className="field">
          取引回数
          <select
            className="select"
            value={nTrades}
            onChange={(e) => setNTrades(Number(e.target.value))}
          >
            {[50, 100, 200, 500, 1000].map((n) => (
              <option key={n} value={n}>
                {n}回
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          資金
          <input
            type="number"
            className="num-input tabular"
            step={100000}
            value={capital}
            onChange={(e) => setCapital(Number(e.target.value))}
          />
        </label>
      </div>

      {/* 期待値の必要条件 */}
      <div className={`verdict ${edgeOk ? 'verdict-ok' : 'verdict-none'}`}>
        <span className="verdict-count tabular">
          {exp > 0 ? '+' : ''}
          {exp.toFixed(3)}R
        </span>
        <span className="verdict-label">
          1取引あたりの期待値。
          {needed != null && (
            <>
              {' '}このR:Rで損益トントンにするのに<strong>必要な勝率は {pct(needed)}</strong>、
              現在の設定は {pct(winRate)}。
            </>
          )}
        </span>
        <p className="verdict-note">
          <strong>勝率だけでは何も決まりません。</strong>
          勝率70%でも1回0.3Rなら、勝率30%で3R取る手法に負けます。
          {!edgeOk && ' 現在の設定は期待値がマイナスです。この状態ではサイズを下げても損失が遅くなるだけで、止まりません。'}
        </p>
      </div>

      {/* 現在設定の結果 */}
      <div className="stat-row">
        <div className="stat">
          <span className="stat-label">破産確率</span>
          <span className={`stat-value tabular ${result.pRuin > 0.05 ? 'down' : ''}`}>
            {pct(result.pRuin)}
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">利益で終わる確率</span>
          <span className="stat-value tabular">{pct(result.pProfit)}</span>
        </div>
        <div className="stat">
          <span className="stat-label">最大DD（中央値）</span>
          <span className="stat-value tabular">{pct(result.medianMaxDrawdown)}</span>
        </div>
        <div className="stat">
          <span className="stat-label">最大DD（95%点）</span>
          <span className={`stat-value tabular ${result.p95MaxDrawdown > 0.3 ? 'down' : ''}`}>
            {pct(result.p95MaxDrawdown)}
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">95%点DDの金額</span>
          <span className="stat-value tabular small">
            −{Math.round(capital * result.p95MaxDrawdown).toLocaleString('ja-JP')}円
          </span>
        </div>
      </div>

      <p className="muted footnote">
        破産は「途中で一度でも資金が半分を割ったか」で判定しています（最終値ではありません）。
        一度割ってから回復した経路も、実際には口座が終わっているためです。
        <strong>95%点の最大ドローダウンが、この計画を実際に続けられるかを決めます</strong>
        — ほとんどの人は破産より遥か手前で降ります。
      </p>

      {/* サイズ別の比較 */}
      <h3>1回のリスク別</h3>
      <div className="table-scroll">
        <table className="quotes">
          <thead>
            <tr>
              <th className="num">1回のリスク</th>
              <th className="num">破産確率</th>
              <th className="num">利益確率</th>
              <th className="num">最大DD中央値</th>
              <th className="num">最大DD 95%点</th>
            </tr>
          </thead>
          <tbody>
            {ladder.map((row) => (
              <tr
                key={row.risk}
                className={Math.abs(row.risk - riskPerTrade) < 1e-9 ? 'clickable-row is-selected' : ''}
              >
                <td className="num tabular">{pct(row.risk)}</td>
                <td className={`num tabular ${row.pRuin > 0.05 ? 'down' : ''}`}>{pct(row.pRuin)}</td>
                <td className="num tabular">{pct(row.pProfit)}</td>
                <td className="num tabular">{pct(row.medianMaxDrawdown)}</td>
                <td className={`num tabular ${row.p95MaxDrawdown > 0.3 ? 'down' : ''}`}>
                  {pct(row.p95MaxDrawdown)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="muted footnote">
        <strong>優位性があってもサイズが大きければ破産します。</strong>
        上の表は勝率・R:Rを固定したまま賭け金だけを変えたものです。期待値は全行で同じなのに、
        破産確率とドローダウンだけが跳ね上がります。
        {kelly > 0 && (
          <>
            {' '}参考までにKelly基準は {pct(kelly)}（ハーフKelly {pct(kelly / 2)}）ですが、
            <strong>これは推奨値ではありません</strong> — Kellyは入力値が正確であることを前提とし、
            数百件のノイズの多い実績から推定すると大幅に賭けすぎになります。
          </>
        )}
      </p>

      <p className="muted footnote">
        シミュレーションは{result.nSimulations.toLocaleString('ja-JP')}回、
        1回あたり{result.nTrades}取引。同じ入力なら必ず同じ結果になります
        （数字が毎回変わると、都合の良い結果が出るまで引き直せてしまうため）。
        なお勝ちを一律{rr.toFixed(2)}R、負けを一律1.0Rとする単純化をしています。
        実際のばらつきはこれより大きく、<strong>本当のドローダウンはここで出る値より深くなります。</strong>
      </p>
    </section>
  );
}
