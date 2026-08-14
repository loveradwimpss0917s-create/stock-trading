import { useEffect, useMemo, useState } from 'react';
import { fetchCandidates, fetchThemes, type Candidate, type Theme } from './api';

const HORIZON_LABEL: Record<string, string> = { day: 'デイ', swing: 'スイング' };

function yen(v: number | null | undefined): string {
  return v == null ? '—' : Number(v).toLocaleString('ja-JP', { maximumFractionDigits: 1 });
}

/** Position size that risks a fixed fraction of capital on the stop.
 * Sizing off the stop distance rather than a flat lot count is what keeps
 * one wide-stop name from dominating the book's risk. */
function shares(capital: number, riskPct: number, entry: number, stop: number): number {
  const risk = entry - stop;
  if (risk <= 0) return 0;
  const units = Math.floor((capital * riskPct) / risk);
  return Math.max(0, Math.floor(units / 100) * 100); // 単元株100株
}

export function CandidatesPanel() {
  const [themes, setThemes] = useState<Theme[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [daysBehind, setDaysBehind] = useState<number | null>(null);
  const [horizon, setHorizon] = useState<'day' | 'swing'>('swing');
  const [themeKey, setThemeKey] = useState<string>('');
  const [capital, setCapital] = useState(1_000_000);
  const [riskPct, setRiskPct] = useState(0.01);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchThemes()
      .then((r) => setThemes(r.themes))
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    setLoading(true);
    fetchCandidates(themeKey || undefined, horizon)
      .then((r) => {
        setCandidates(r.candidates);
        setAsOf(r.as_of);
        setDaysBehind(r.days_behind);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [themeKey, horizon]);

  const visibleThemes = useMemo(
    () => themes.filter((t) => t.horizon === horizon || t.horizon === 'both'),
    [themes, horizon]
  );

  const grouped = useMemo(() => {
    const map = new Map<string, Candidate[]>();
    for (const c of candidates) {
      const list = map.get(c.theme_key) ?? [];
      list.push(c);
      map.set(c.theme_key, list);
    }
    // Factor themes lead: they answer "what is setting up right now", which is
    // the question this tab exists for. Sector themes narrow within an
    // industry and read better as the second half of the page.
    return [...map.entries()].sort(([, a], [, b]) => {
      const kind = (c: Candidate) => (c.theme_kind === 'factor' ? 0 : 1);
      return kind(a[0]!) - kind(b[0]!) || (a[0]!.theme_sort_order ?? 0) - (b[0]!.theme_sort_order ?? 0);
    });
  }, [candidates]);

  // Twenty themes at ten names each is 200 rows — unreadable as a landing
  // view. Showing every theme's leaders keeps the page scannable, and picking
  // a single theme opens it up to the full list.
  const showAll = themeKey !== '';
  const PREVIEW_ROWS = 5;

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>売買候補</h2>
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

      {asOf && (
        <div className={`asof ${daysBehind && daysBehind > 7 ? 'asof-stale' : 'asof-fresh'}`}>
          基準日 <span className="tabular">{asOf}</span>
          {daysBehind != null && daysBehind > 7 && (
            <>
              {' '}
              （<span className="tabular">{daysBehind}日前</span>）—
              これは<strong>その日時点</strong>の候補です。本日の候補ではありません。
              有料プラン契約後は同じ画面が当日基準になります。
            </>
          )}
        </div>
      )}

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
      {!loading && candidates.length === 0 && (
        <p className="muted">
          候補がありません。特徴量とスクリーニングのジョブを実行してください。
        </p>
      )}

      {grouped.map(([key, list]) => (
        <div key={key} className="theme-block">
          <h3 className="theme-title">
            {list[0]?.theme_name}
            <span className="theme-kind">{list[0]?.theme_kind === 'sector' ? '業種' : 'ファクター'}</span>
          </h3>
          <p className="muted theme-desc">{list[0]?.theme_description}</p>
          <div className="table-scroll">
            <table className="quotes">
              <thead>
                <tr>
                  <th>#</th>
                  <th>銘柄</th>
                  <th className="num">基準終値</th>
                  <th className="num">損切り</th>
                  <th className="num">目標</th>
                  <th className="num">R:R</th>
                  <th className="num">株数</th>
                  <th className="num">必要資金</th>
                  <th>根拠</th>
                </tr>
              </thead>
              <tbody>
                {(showAll ? list : list.slice(0, PREVIEW_ROWS)).map((c) => {
                  const qty = shares(capital, riskPct, c.entry_ref, c.stop_price);
                  const components = Object.entries(c.rationale?.components ?? {})
                    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
                    .slice(0, 2)
                    .map(([k]) => k);
                  return (
                    <tr key={c.code}>
                      <td className="tabular">{c.rank}</td>
                      <td>
                        <span className="tabular code">{c.ticker4}</span> {c.name_ja}
                      </td>
                      <td className="num tabular">{yen(c.entry_ref)}</td>
                      <td className="num tabular down">{yen(c.stop_price)}</td>
                      <td className="num tabular up">{yen(c.target_price)}</td>
                      <td className="num tabular">{c.rr_ratio?.toFixed(2)}</td>
                      <td className="num tabular">{qty ? qty.toLocaleString('ja-JP') : '—'}</td>
                      <td className="num tabular">
                        {qty ? yen(Math.round(qty * c.entry_ref)) : '—'}
                      </td>
                      <td className="reasons">{components.join(' / ') || '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {!showAll && list.length > PREVIEW_ROWS && (
            <button className="link-btn" onClick={() => setThemeKey(key)}>
              このテーマの{list.length}件をすべて表示 →
            </button>
          )}
        </div>
      ))}

      <p className="muted footnote">
        損切り・目標はATR（平均的な値幅）の倍数です。株数は「損切りに当たったとき資金の
        {(riskPct * 100).toFixed(1)}%を失う」逆算で、単元株100株に丸めています。
        これらのテーマは<strong>統計的検証を通過していません</strong>（上の検証パネル参照）。
        銘柄の絞り込み手段であって、優位性が確認された戦略ではありません。
      </p>
    </section>
  );
}
