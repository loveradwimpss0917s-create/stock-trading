import { useEffect, useState } from 'react';
import { fetchHome, type HomeAction, type HomeResponse, type Position, type TradePlan } from './api';
import { PlanDetailModal } from './PlanDetailModal';
import { PositionDetailModal } from './PositionDetailModal';

const REGIME_LABEL: Record<string, { text: string; cls: string }> = {
  offense: { text: '攻め寄り', cls: 'tone-ok' },
  defense: { text: '守り寄り', cls: 'tone-bad' },
  neutral: { text: '中立', cls: 'tone-warn' },
};

function yen(v: number | string | null | undefined): string {
  if (v == null) return '—';
  return Number(v).toLocaleString('ja-JP', { maximumFractionDigits: 1 });
}

function ActionRow({ action, onOpen }: { action: HomeAction; onOpen: (kind: string, id: number) => void }) {
  return (
    <button className="action-row" onClick={() => onOpen(action.kind, action.ref_id)}>
      <span className={`action-dot action-${action.kind}`} />
      <span>{action.message}</span>
    </button>
  );
}

export function HomePanel() {
  const [data, setData] = useState<HomeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openPlanId, setOpenPlanId] = useState<number | null>(null);
  const [openPositionId, setOpenPositionId] = useState<number | null>(null);

  const load = () => {
    setLoading(true);
    fetchHome()
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const openAction = (kind: string, id: number) => {
    if (kind === 'record_entry') setOpenPlanId(id);
    else if (kind === 'expiring') setOpenPlanId(id);
    else if (kind === 'review_stop') setOpenPositionId(id);
  };

  if (loading && !data) return <p className="muted">読み込み中…</p>;
  if (error) return <p className="status-error">エラー: {error}</p>;
  if (!data) return null;

  const regime = data.regime;
  const regimeLabel = regime ? REGIME_LABEL[regime.regime_label] : null;
  const heatPct = data.max_heat ? (data.portfolio_heat / data.max_heat) * 100 : 0;

  return (
    <section className="home">
      {/* アクション */}
      <div className="panel home-actions">
        <h2>本日のアクション</h2>
        {data.actions.length === 0 ? (
          <p className="muted">対応が必要な項目はありません。</p>
        ) : (
          <div className="action-list">
            {data.actions.map((a, i) => (
              <ActionRow key={i} action={a} onOpen={openAction} />
            ))}
          </div>
        )}
      </div>

      {/* 保有中 */}
      <div className="panel">
        <div className="panel-head">
          <h2>保有中</h2>
          <span className="muted tabular">{data.open_positions.length}件</span>
        </div>
        <div className="heat-bar-row">
          <span className="muted">Portfolio heat</span>
          <div className="heat-bar">
            <div
              className={`heat-bar-fill ${heatPct >= 90 ? 'heat-danger' : heatPct >= 60 ? 'heat-warn' : ''}`}
              style={{ width: `${Math.min(heatPct, 100)}%` }}
            />
          </div>
          <span className="tabular">
            {(data.portfolio_heat * 100).toFixed(2)}% / {(data.max_heat * 100).toFixed(1)}%
          </span>
        </div>

        {data.open_positions.length === 0 ? (
          <p className="muted">保有ポジションはありません。</p>
        ) : (
          <div className="table-scroll">
            <table className="quotes">
              <thead>
                <tr>
                  <th>銘柄</th>
                  <th className="num">建値</th>
                  <th className="num">現在値</th>
                  <th className="num">損切り</th>
                  <th className="num">R</th>
                  <th className="num">残リスク</th>
                </tr>
              </thead>
              <tbody>
                {data.open_positions.map((p: Position) => (
                  <tr key={p.id} className="clickable-row" onClick={() => setOpenPositionId(p.id)}>
                    <td>
                      <span className="tabular code">{p.ticker4}</span> {p.security_name}
                    </td>
                    <td className="num tabular">{yen(p.entry_price)}</td>
                    <td className="num tabular">{yen(p.current_price)}</td>
                    <td className="num tabular down">{yen(p.stop_current)}</td>
                    <td className={`num tabular ${Number(p.current_r ?? 0) >= 0 ? 'up' : 'down'}`}>
                      {p.current_r == null ? '—' : `${Number(p.current_r) >= 0 ? '+' : ''}${Number(p.current_r).toFixed(2)}R`}
                    </td>
                    <td className="num tabular">{yen(p.current_risk)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 監視中の計画 */}
      <div className="panel">
        <h2>監視中の計画</h2>
        {data.triggered_awaiting_entry.length === 0 && data.armed_watching.length === 0 ? (
          <p className="muted">監視中の計画はありません。</p>
        ) : (
          <div className="table-scroll">
            <table className="quotes">
              <thead>
                <tr>
                  <th>銘柄</th>
                  <th>Setup</th>
                  <th>状態</th>
                  <th className="num">トリガー</th>
                  <th className="num">損切り</th>
                  <th className="num">R:R</th>
                  <th className="num">期限</th>
                </tr>
              </thead>
              <tbody>
                {[...data.triggered_awaiting_entry, ...data.armed_watching].map((p: TradePlan) => (
                  <tr key={p.id} className="clickable-row" onClick={() => setOpenPlanId(p.id)}>
                    <td>
                      <span className="tabular code">{p.ticker4}</span> {p.security_name}
                    </td>
                    <td className="muted">{p.setup_name}</td>
                    <td>
                      <span className={`pill state-${p.state}`}>
                        {p.state === 'triggered' ? '▲ 到達' : '監視中'}
                      </span>
                    </td>
                    <td className="num tabular">{yen(p.trigger_price)}</td>
                    <td className="num tabular down">{yen(p.stop_planned)}</td>
                    <td className="num tabular">{Number(p.expected_rr).toFixed(2)}</td>
                    <td className="num tabular">{p.expires_on}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 市場環境 */}
      <div className="panel">
        <h2>市場環境</h2>
        {!regime ? (
          <p className="muted">まだ計算されていません。</p>
        ) : (
          <>
            <div className="regime-row">
              <span className={`pill ${regimeLabel?.cls}`}>{regimeLabel?.text}</span>
              <span className="tabular">
                25日線超え <strong>{(regime.pct_above_ma25 * 100).toFixed(0)}%</strong>
              </span>
              <span className="tabular">
                値上がり比率 <strong>{(regime.adv_decline_ratio * 100).toFixed(0)}%</strong>
              </span>
              <span className="tabular">
                新高値−新安値 <strong>{regime.new_high_minus_low >= 0 ? '+' : ''}{regime.new_high_minus_low}</strong>
              </span>
            </div>
            <p className="muted footnote">
              指数を取得していないため、保有{regime.computed_from_n.toLocaleString('ja-JP')}銘柄自身のBreadthから構成しています。
              このラベルは<strong>記録用であり、取引を止める判断には使いません</strong>
              （有効性が未検証のため）。
            </p>
          </>
        )}
      </div>

      {/* 新規候補 */}
      <div className="panel">
        <h2>新規候補</h2>
        {data.new_candidates.length === 0 ? (
          <p className="muted">本日、条件を満たす候補はありません。これは正常な結果です。</p>
        ) : (
          <div className="table-scroll">
            <table className="quotes">
              <thead>
                <tr>
                  <th>銘柄</th>
                  <th>Setup</th>
                  <th className="num">基準終値</th>
                  <th className="num">トリガー</th>
                  <th className="num">R:R</th>
                </tr>
              </thead>
              <tbody>
                {data.new_candidates.map((p: TradePlan) => (
                  <tr key={p.id} className="clickable-row" onClick={() => setOpenPlanId(p.id)}>
                    <td>
                      <span className="tabular code">{p.ticker4}</span> {p.security_name}
                    </td>
                    <td className="muted">{p.setup_name}</td>
                    <td className="num tabular">{yen(p.reference_close)}</td>
                    <td className="num tabular">{yen(p.trigger_price)}</td>
                    <td className="num tabular">{Number(p.expected_rr).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted footnote">
          機械的な条件を満たした銘柄です。買う理由（thesis）はまだ書かれていません — クリックして記入し、判断してください。
        </p>
      </div>

      {openPlanId != null && (
        <PlanDetailModal
          planId={openPlanId}
          onClose={() => setOpenPlanId(null)}
          onChanged={load}
        />
      )}
      {openPositionId != null && (
        <PositionDetailModal
          positionId={openPositionId}
          onClose={() => setOpenPositionId(null)}
          onChanged={load}
        />
      )}
    </section>
  );
}
