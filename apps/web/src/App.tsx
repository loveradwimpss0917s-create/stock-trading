import { useEffect, useState } from 'react';

interface HealthResponse {
  status: string;
  service: string;
  time: string;
}

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/health')
      .then((res) => {
        if (!res.ok) throw new Error(`API returned ${res.status}`);
        return res.json() as Promise<HealthResponse>;
      })
      .then(setHealth)
      .catch((err) => setError(err.message));
  }, []);

  return (
    <main className="page">
      <div className="banner">
        12週間遅延データに基づく研究結果であり、売買推奨ではありません。
      </div>

      <header className="header">
        <h1>kabu-quant</h1>
        <p className="subtitle">日本株クオンツ分析 — 研究基盤</p>
      </header>

      <section className="status-card">
        <h2>API接続状況</h2>
        {error && <p className="status status-error">✕ 接続エラー: {error}</p>}
        {!error && !health && <p className="status">確認中…</p>}
        {health && (
          <>
            <p className="status status-ok">✓ 接続成功</p>
            <dl className="status-detail">
              <dt>service</dt>
              <dd>{health.service}</dd>
              <dt>time</dt>
              <dd className="tabular">{health.time}</dd>
            </dl>
          </>
        )}
      </section>
    </main>
  );
}

export default App;
