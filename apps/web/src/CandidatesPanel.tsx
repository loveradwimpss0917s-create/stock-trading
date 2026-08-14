import { useEffect, useMemo, useState } from 'react';
import { fetchCandidates, fetchThemes, type Candidate, type Theme } from './api';

const HORIZON_LABEL: Record<string, string> = { day: 'デイ', swing: 'スイング' };

/** The scorer's component keys are internal names (ret_20d, adx_14). Showing
 * them raw asks the reader to learn the codebase's vocabulary, so each gets a
 * Japanese label and a longer note used as a tooltip. A test in
 * test_screening.py reads this map and fails if the scorer grows a component
 * that has no label here. */
const COMPONENT_LABEL: Record<string, { short: string; note: string }> = {
  ret_1d: { short: '前日騰落', note: '前日の騰落率。上げた銘柄ほど上位' },
  ret_5d: { short: '5日騰落', note: '直近5営業日の騰落率。上げた銘柄ほど上位' },
  ret_20d: { short: '20日騰落', note: '直近20営業日（約1か月）の騰落率。上げた銘柄ほど上位' },
  ret_1d_neg: { short: '前日の下げ', note: '前日の下落幅。下げた銘柄ほど上位（逆張り）' },
  ret_5d_neg: { short: '5日の下げ', note: '直近5営業日の下落幅。下げた銘柄ほど上位（押し目）' },
  dist_52w_high: { short: '52週高値接近', note: '52週高値までの距離。高値に近いほど上位' },
  adx_14: { short: 'トレンドの強さ', note: 'ADX(14)。上下の方向は問わず、トレンドが明確なほど上位' },
  rsi_oversold: { short: '売られすぎ', note: 'RSI(14)が50より低いほど上位' },
  atr_pct: { short: '値幅率', note: 'ATR(14)÷株価。1日に動く幅が大きいほど上位' },
  vol_20d: { short: 'ボラティリティ', note: '20日間の変動の大きさ。大きいほど上位' },
  abs_ret_1d: { short: '前日の変動幅', note: '前日の値動きの大きさ。方向は問わない' },
  above_ma25: { short: '25日線より上', note: '終値が25日移動平均を上回れば1、下回れば0' },
  above_ma75: { short: '75日線より上', note: '終値が75日移動平均を上回れば1、下回れば0' },
};

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
                  // Top two by absolute contribution, but the sign is kept: a
                  // large negative contribution held the name back, and
                  // labelling it the same as a positive one would misread.
                  const components = Object.entries(c.rationale?.components ?? {})
                    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
                    .slice(0, 2);
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
                      <td className="reasons">
                        {components.length === 0
                          ? '—'
                          : components.map(([k, v]) => {
                              const label = COMPONENT_LABEL[k];
                              return (
                                <span
                                  key={k}
                                  className={`reason ${v >= 0 ? 'up' : 'down'}`}
                                  title={
                                    label
                                      ? `${label.note}（寄与 ${v >= 0 ? '+' : ''}${v.toFixed(2)}）`
                                      : k
                                  }
                                >
                                  {v >= 0 ? '▲' : '▼'} {label?.short ?? k}
                                </span>
                              );
                            })}
                      </td>
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
        <strong>根拠欄</strong>は、その銘柄の順位を最も動かした要因を上位2つ表示しています。
        ▲は順位を押し上げた要因、▼は押し下げた要因です（項目名にカーソルを合わせると説明が出ます）。
        各要因は<strong>その日の全銘柄の中での偏差</strong>（Zスコア）であって、生の数値ではありません。
        「20日騰落が+15%」ではなく「20日騰落が平均より上位」という意味です。
        円建てのATRとポイント建てのRSIを足し合わせられるようにするための処理です。
      </p>
      <p className="muted footnote">
        損切り・目標はATR（平均的な値幅）の倍数です。株数は「損切りに当たったとき資金の
        {(riskPct * 100).toFixed(1)}%を失う」逆算で、単元株100株に丸めています。
        これらのテーマは<strong>統計的検証を通過していません</strong>（上の検証パネル参照）。
        銘柄の絞り込み手段であって、優位性が確認された戦略ではありません。
      </p>
    </section>
  );
}
