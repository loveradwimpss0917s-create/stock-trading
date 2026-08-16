import { useEffect, useState } from 'react';
import { fetchPlans, type TradePlan } from './api';
import { PlanDetailModal } from './PlanDetailModal';

const STATE_TABS: { value: string; label: string }[] = [
  { value: 'draft', label: '新規候補' },
  { value: 'armed,triggered', label: '監視中' },
  { value: 'open', label: '建玉中' },
  { value: '', label: 'すべて' },
];

const STATE_LABEL: Record<string, string> = {
  draft: '未判断',
  armed: '監視中',
  triggered: '到達',
  open: '建玉中',
  closed: '決済済み',
  expired: '期限切れ',
  invalidated: '反証成立',
  passed: '見送り',
  discarded: '破棄',
};

function yen(v: number | string | null | undefined): string {
  if (v == null) return '—';
  return Number(v).toLocaleString('ja-JP', { maximumFractionDigits: 1 });
}

export function PlansPanel() {
  const [tab, setTab] = useState<string>('draft');
  const [plans, setPlans] = useState<TradePlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);

  const load = () => {
    setLoading(true);
    fetchPlans(tab || undefined)
      .then((r) => setPlans(r.plans))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(load, [tab]);

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>計画一覧</h2>
        <div className="seg">
          {STATE_TABS.map((t) => (
            <button
              key={t.value}
              className={`seg-btn${tab === t.value ? ' is-active' : ''}`}
              onClick={() => setTab(t.value)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="status-error">{error}</p>}
      {loading && <p className="muted">読み込み中…</p>}
      {!loading && plans.length === 0 && <p className="muted">該当する計画はありません。</p>}

      {plans.length > 0 && (
        <div className="table-scroll">
          <table className="quotes">
            <thead>
              <tr>
                <th>基準日</th>
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
              {plans.map((p) => (
                <tr key={p.id} className="clickable-row" onClick={() => setOpenId(p.id)}>
                  <td className="tabular">{p.created_on}</td>
                  <td>
                    <span className="tabular code">{p.ticker4}</span> {p.security_name}
                  </td>
                  <td className="muted">{p.setup_name}</td>
                  <td>
                    <span className={`pill state-${p.state}`}>{STATE_LABEL[p.state] ?? p.state}</span>
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

      {openId != null && (
        <PlanDetailModal planId={openId} onClose={() => setOpenId(null)} onChanged={load} />
      )}
    </section>
  );
}
