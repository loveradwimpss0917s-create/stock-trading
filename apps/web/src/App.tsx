import { useEffect, useRef, useState } from 'react';
import {
  fetchFreshness,
  fetchStock,
  fetchStocks,
  fetchStrategies,
  fetchSyncStatus,
  type DailyQuote,
  type Freshness,
  type Security,
  type StrategyResult,
  type SyncStatus,
} from './api';
import { PriceChart } from './PriceChart';
import { StrategyPanel } from './StrategyPanel';

function pctChange(quotes: DailyQuote[]): number | null {
  const closes = quotes.map((q) => (q.close === null ? NaN : Number(q.close))).filter((v) => !Number.isNaN(v));
  if (closes.length < 2) return null;
  const first = closes[0]!;
  const last = closes[closes.length - 1]!;
  return first === 0 ? null : ((last - first) / first) * 100;
}

export default function App() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [query, setQuery] = useState('');
  const [stocks, setStocks] = useState<Security[]>([]);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ security: Security; quotes: DailyQuote[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [strategies, setStrategies] = useState<StrategyResult[]>([]);
  const [passedCount, setPassedCount] = useState(0);
  const [freshness, setFreshness] = useState<Freshness | null>(null);

  useEffect(() => {
    fetchSyncStatus().then(setStatus).catch((e) => setError(String(e)));
    fetchFreshness().then(setFreshness).catch(() => {});
    fetchStrategies()
      .then((res) => {
        setStrategies(res.strategies);
        setPassedCount(res.passed_count);
      })
      .catch(() => {});
  }, []);

  // Debounced so typing a code doesn't fire a request per keystroke.
  const requestId = useRef(0);
  useEffect(() => {
    const id = ++requestId.current;
    setSearching(true);
    const timer = setTimeout(() => {
      fetchStocks(query.trim() || undefined)
        .then((res) => {
          // Ignore a slow response that a newer query has already superseded.
          if (id !== requestId.current) return;
          setStocks(res.stocks);
          setSelected((prev) =>
            prev && res.stocks.some((s) => s.code === prev) ? prev : (res.stocks[0]?.code ?? null)
          );
        })
        .catch((e) => id === requestId.current && setError(String(e)))
        .finally(() => id === requestId.current && setSearching(false));
    }, 250);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
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
        <strong>売買には使えません。</strong>{' '}
        {freshness?.days_behind != null ? (
          <>
            最新データは <span className="tabular">{freshness.latest_date}</span>（
            <span className="tabular">{freshness.days_behind}日前</span>
            ）。J-Quants Freeは12週間遅延のため、常にこの状態です。
          </>
        ) : (
          <>12週間遅延データに基づく研究結果であり、売買推奨ではありません。</>
        )}{' '}
        本アプリの用途は「その戦略は統計的に本物か」の検証です。
      </div>

      <header className="header">
        <h1>kabu-quant</h1>
        <p className="subtitle">日本株クオンツ分析 — 研究基盤</p>
      </header>

      {error && <p className="status-error">エラー: {error}</p>}

      <StrategyPanel strategies={strategies} passedCount={passedCount} />

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
        <nav className="list-panel" aria-label="銘柄一覧">
          <input
            type="search"
            className="search"
            placeholder="銘柄コード・社名で検索（例: 7203, トヨタ）"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="銘柄検索"
          />
          <p className="list-hint">
            {query.trim()
              ? searching
                ? '検索中…'
                : `${stocks.length}件${stocks.length >= 100 ? '以上' : ''}（全${status?.securities_count.toLocaleString() ?? '—'}銘柄から検索）`
              : '日足取得済みの銘柄'}
          </p>

          <div className="list">
            {stocks.length === 0 && !searching && (
              <p className="muted pad">該当する銘柄がありません。</p>
            )}
            {stocks.map((s) => (
              <button
                key={s.code}
                className={`list-item${s.code === selected ? ' is-selected' : ''}`}
                onClick={() => setSelected(s.code)}
              >
                <span className="tabular code">{s.ticker4}</span>
                <span className="name">{s.name_ja ?? s.name_en ?? s.code}</span>
                {s.has_data === false && <span className="badge">未取得</span>}
              </button>
            ))}
          </div>
        </nav>

        <section className="detail">
          {!detail && selected && <p className="muted">読み込み中…</p>}
          {!selected && <p className="muted">銘柄を選択してください。</p>}
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

              {detail.quotes.length === 0 ? (
                <p className="notice">
                  この銘柄の日足はまだ取得していません。現在は10銘柄のみバックフィル済みです
                  （全銘柄の取得にはJ-Quants Freeのレート制限下で長時間を要します）。
                </p>
              ) : (
                <>
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
            </>
          )}
        </section>
      </div>
    </main>
  );
}
