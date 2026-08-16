import { useEffect, useState } from 'react';
import { fetchPositions, type Position } from './api';
import { PositionDetailModal } from './PositionDetailModal';

function yen(v: number | string | null | undefined): string {
  if (v == null) return '—';
  return Number(v).toLocaleString('ja-JP', { maximumFractionDigits: 1 });
}

export function PositionsPanel() {
  const [status, setStatus] = useState<'open' | 'closed'>('open');
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);

  const load = () => {
    setLoading(true);
    fetchPositions(status)
      .then((r) => setPositions(r.positions))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(load, [status]);

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>建玉</h2>
        <div className="seg">
          {(['open', 'closed'] as const).map((s) => (
            <button
              key={s}
              className={`seg-btn${status === s ? ' is-active' : ''}`}
              onClick={() => setStatus(s)}
            >
              {s === 'open' ? '保有中' : '決済済み'}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="status-error">{error}</p>}
      {loading && <p className="muted">読み込み中…</p>}
      {!loading && positions.length === 0 && <p className="muted">該当する建玉はありません。</p>}

      {positions.length > 0 && (
        <div className="table-scroll">
          <table className="quotes">
            <thead>
              <tr>
                <th>建玉日</th>
                <th>銘柄</th>
                <th className="num">建値</th>
                <th className="num">{status === 'open' ? '現在値' : '決済値'}</th>
                <th className="num">株数</th>
                <th className="num">R</th>
                {status === 'closed' && <th className="num">損益(円)</th>}
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => {
                const r = status === 'open' ? p.current_r : p.r_multiple;
                return (
                  <tr key={p.id} className="clickable-row" onClick={() => setOpenId(p.id)}>
                    <td className="tabular">{p.opened_on}</td>
                    <td>
                      <span className="tabular code">{p.ticker4}</span> {p.security_name}
                    </td>
                    <td className="num tabular">{yen(p.entry_price)}</td>
                    <td className="num tabular">{yen(status === 'open' ? p.current_price : p.exit_price)}</td>
                    <td className="num tabular">{p.shares.toLocaleString('ja-JP')}</td>
                    <td className={`num tabular ${Number(r ?? 0) >= 0 ? 'up' : 'down'}`}>
                      {r == null ? '—' : `${Number(r) >= 0 ? '+' : ''}${Number(r).toFixed(2)}R`}
                    </td>
                    {status === 'closed' && (
                      <td className={`num tabular ${Number(p.pnl_yen ?? 0) >= 0 ? 'up' : 'down'}`}>
                        {yen(p.pnl_yen)}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {openId != null && (
        <PositionDetailModal positionId={openId} onClose={() => setOpenId(null)} onChanged={load} />
      )}
    </section>
  );
}
