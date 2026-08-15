import { useEffect, useMemo, useState } from 'react';
import { fetchThemePerformance, type ThemePerformance } from './api';

const HORIZON_LABEL: Record<string, string> = { day: 'デイ', swing: 'スイング' };

/** Below this many trades a hit rate is noise dressed up as a number. */
const MIN_TRADES_TO_READ = 30;

function pct(v: number | null): string {
  return v == null ? '—' : `${(v * 100).toFixed(1)}%`;
}

export function ThemePerformancePanel() {
  const [rows, setRows] = useState<ThemePerformance[]>([]);
  const [horizon, setHorizon] = useState<'day' | 'swing'>('swing');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchThemePerformance()
      .then((r) => setRows(r.performance))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  // Ranked by average R rather than by win rate: a theme that is right 30% of
  // the time for 3R beats one that is right 70% of the time for 0.3R, and
  // sorting by hit rate would put the second one on top.
  const visible = useMemo(
    () =>
      rows
        .filter((r) => r.horizon === horizon)
        .sort((a, b) => (b.avg_r ?? -Infinity) - (a.avg_r ?? -Infinity)),
    [rows, horizon]
  );

  const period = rows.length
    ? `${rows.reduce((m, r) => (r.first_as_of && r.first_as_of < m ? r.first_as_of : m), '9999')} 〜 ${rows.reduce((m, r) => (r.last_as_of && r.last_as_of > m ? r.last_as_of : m), '0000')}`
    : null;

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>テーマ別の結果</h2>
        <div className="seg">
          {(['swing', 'day'] as const).map((h) => (
            <button
              key={h}
              className={`seg-btn${horizon === h ? ' is-active' : ''}`}
              onClick={() => setHorizon(h)}
            >
              {HORIZON_LABEL[h]}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="status-error">エラー: {error}</p>}
      {loading && <p className="muted">読み込み中…</p>}
      {!loading && rows.length === 0 && (
        <p className="muted">
          結果がまだありません。evaluate-candidates ジョブを実行してください。
        </p>
      )}

      {visible.length > 0 && (
        <>
          <div className="asof asof-stale">
            これは<strong>過去に同じ画面を出していたら</strong>どうなっていたかの再現です
            {period && <>（{period}）</>}。
            候補は各基準日時点の情報だけで作り、<strong>翌営業日の寄り付きで約定</strong>したものとして、
            損切り・目標・保有期限のどれに当たったかを日足で判定しています。
            <strong>検証期間と、テーマを作るときに見ていた期間が同じ</strong>なので、
            将来も同じ成績が出る証拠ではありません。
          </div>

          <div className="table-scroll">
            <table className="quotes">
              <thead>
                <tr>
                  <th>テーマ</th>
                  <th className="num">平均損益(R)</th>
                  <th className="num">勝率</th>
                  <th className="num">件数</th>
                  <th className="num">目標到達</th>
                  <th className="num">損切り</th>
                  <th className="num">期限切れ</th>
                  <th className="num">見送り</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => {
                  const thin = r.n_trades < MIN_TRADES_TO_READ;
                  return (
                    <tr key={`${r.theme_key}/${r.horizon}`}>
                      <td>
                        {r.theme_name}
                        <span className="theme-kind">
                          {r.theme_kind === 'sector' ? '業種' : 'ファクター'}
                        </span>
                        {thin && <span className="theme-kind">件数不足</span>}
                      </td>
                      <td
                        className={`num tabular ${(r.avg_r ?? 0) > 0 ? 'up' : 'down'}`}
                        title="1回の取引で、損切り幅の何倍を得たか（平均）"
                      >
                        {r.avg_r == null ? '—' : `${r.avg_r > 0 ? '+' : ''}${r.avg_r.toFixed(2)}R`}
                      </td>
                      <td className="num tabular">{pct(r.win_rate)}</td>
                      <td className="num tabular">{r.n_trades.toLocaleString('ja-JP')}</td>
                      <td className="num tabular up">{r.n_target}</td>
                      <td className="num tabular down">{r.n_stop}</td>
                      <td className="num tabular">{r.n_timeout}</td>
                      <td className="num tabular" title="翌寄りが既に損切り水準を割っていて建てられなかった回数">
                        {r.n_no_entry}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <p className="muted footnote">
            <strong>Rとは</strong>：損切りまでの距離を1とした単位です。+1Rは「損切り幅と同じだけ儲かった」、
            −1Rは「損切りに当たった」を意味します。株価も損切り幅も銘柄ごとに違うので、
            円ではなくこの単位で揃えないとテーマ同士を比べられません。
          </p>
          <p className="muted footnote">
            <strong>勝率ではなく平均損益(R)で並べています。</strong>
            勝率70%でも1回の利益が0.3Rなら、勝率30%で3R取るテーマに負けます。
            勝率だけを見ると判断を誤ります。
            件数が{MIN_TRADES_TO_READ}件未満のテーマには「件数不足」と付けています —
            数字は出ますが、偶然と区別できません。
          </p>
          <p className="muted footnote">
            日足しか無いため、<strong>同じ日に損切りと目標の両方に触れた場合は損切り扱い</strong>です。
            どちらが先だったか分からない以上、有利な方に数えると成績が水増しされます。
            窓開けで損切り水準を飛び越えた場合は、損切り値ではなく<strong>実際の寄り値</strong>で
            決済したものとして計算しています（−1Rより悪くなります）。
          </p>
        </>
      )}
    </section>
  );
}
