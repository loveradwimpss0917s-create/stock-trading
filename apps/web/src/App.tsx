import { useEffect, useState } from 'react';
import {
  fetchStock,
  fetchStocks,
  fetchSyncStatus,
  type DailyQuote,
  type Security,
  type SyncStatus,
} from './api';
import { PriceChart } from './PriceChart';

function pctChange(quotes: DailyQuote[]): number | null {
  const closes = quotes.map((q) => (q.close === null ? NaN : Number(q.close))).filter((v) => !Number.isNaN(v));
  if (closes.length < 2) return null;
  const first = closes[0]!;
  const last = closes[closes.length - 1]!;
  return first === 0 ? null : ((last - first) / first) * 100;
}

export default function App() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [stocks, setStocks] = useState<Security[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ security: Security; quotes: DailyQuote[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchSyncStatus(), fetchStocks()])
      .then(([s, list]) => {
        setStatus(s);
        setStocks(list.stocks);
        if (list.stocks.length > 0) setSelected(list.stocks[0]!.code);
      })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setDetail(null);
    fetchStock(selected)
      .then(setDetail)
      .catch((e) => setError(String(e)));
  }, [selected]);

  const change = detail ? pctChange(detail.quotes) : null;
  const latest = detail?.quotes[detail.quotes.length - 1];

  return (
    <main className="page">
      <div className="banner">
        12週間遅延データに基づく研究結果であり、売買推奨ではありません。
      </div>

      <header className="header">
        <h1>kabu-quant</h1>
        <p className="subtitle">日本株クオンツ分析 — 研究基盤</p>
      </header>

      {error && <p className="status-error">エラー: {error}</p>}

      {status && (
        <section className="stat-row">
          <div className="stat">
            <span className="stat-label">銘柄マスタ</span>
            <span className="stat-value tabular">{status.securities_count.toLocaleString()}</span>
          </div>
          <div className="stat">
            <span className="stat-label">日足レコード</span>
            <span className="stat-value tabular">{status.daily_quotes_count.toLocaleString()}</span>
          </div>
          <div className="stat">
            <span className="stat-label">取得済み銘柄</span>
            <span className="stat-value tabular">{status.covered_codes.toLocaleString()}</span>
          </div>
          <div className="stat">
            <span className="stat-label">データ期間</span>
            <span className="stat-value tabular small">
              {status.earliest_date} 〜 {status.latest_date}
            </span>
          </div>
        </section>
      )}

      <div className="layout">
        <nav className="list" aria-label="銘柄一覧">
          {stocks.length === 0 && !error && <p className="muted">読み込み中…</p>}
          {stocks.map((s) => (
            <button
              key={s.code}
              className={`list-item${s.code === selected ? ' is-selected' : ''}`}
              onClick={() => setSelected(s.code)}
            >
              <span className="tabular code">{s.ticker4}</span>
              <span className="name">{s.name_ja ?? s.name_en ?? s.code}</span>
            </button>
          ))}
        </nav>

        <section className="detail">
          {!detail && selected && <p className="muted">読み込み中…</p>}
          {detail && (
            <>
              <div className="detail-head">
                <div>
                  <h2>{detail.security.name_ja ?? detail.security.code}</h2>
                  <p className="muted">
                    {detail.security.ticker4} · {detail.security.name_en ?? '—'} ·{' '}
                    {detail.security.scale_category ?? '—'}
                  </p>
                </div>
                {latest && (
                  <div className="price">
                    <span className="price-value tabular">
                      {Number(latest.close).toLocaleString('ja-JP')}
                    </span>
                    {change !== null && (
                      <span className={`price-change tabular ${change >= 0 ? 'up' : 'down'}`}>
                        {change >= 0 ? '+' : ''}
                        {change.toFixed(2)}%
                      </span>
                    )}
                  </div>
                )}
              </div>

              <PriceChart quotes={detail.quotes} />

              <table className="quotes">
                <thead>
                  <tr>
                    <th>日付</th>
                    <th className="num">始値</th>
                    <th className="num">高値</th>
                    <th className="num">安値</th>
                    <th className="num">終値</th>
                    <th className="num">出来高</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.quotes
                    .slice()
                    .reverse()
                    .slice(0, 15)
                    .map((q) => (
                      <tr key={q.date}>
                        <td className="tabular">{q.date}</td>
                        <td className="num tabular">{Number(q.open).toLocaleString('ja-JP')}</td>
                        <td className="num tabular">{Number(q.high).toLocaleString('ja-JP')}</td>
                        <td className="num tabular">{Number(q.low).toLocaleString('ja-JP')}</td>
                        <td className="num tabular">{Number(q.close).toLocaleString('ja-JP')}</td>
                        <td className="num tabular">{q.volume?.toLocaleString('ja-JP') ?? '—'}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
