import { useEffect, useMemo, useState } from 'react';
import { fetchThemePerformance, type Baseline, type ThemePerformance } from './api';

const HORIZON_LABEL: Record<string, string> = { day: 'デイ', swing: 'スイング' };

/** Below this many trades a hit rate is noise dressed up as a number. */
const MIN_TRADES_TO_READ = 30;

function pct(v: number | null): string {
  return v == null ? '—' : `${(v * 100).toFixed(1)}%`;
}

export function ThemePerformancePanel() {
  const [rows, setRows] = useState<ThemePerformance[]>([]);
  const [baselines, setBaselines] = useState<Baseline[]>([]);
  const [horizon, setHorizon] = useState<'day' | 'swing'>('swing');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchThemePerformance()
      .then((r) => {
        setRows(r.performance);
        setBaselines(r.baseline);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  // Ranked by edge over the baseline, not by raw R. In a rising market every
  // long-only theme posts a positive R, so sorting by that ranks themes by how
  // much market they held, not by how well they picked.
  const visible = useMemo(
    () =>
      rows
        .filter((r) => r.horizon === horizon)
        .sort((a, b) => (b.edge_r ?? -Infinity) - (a.edge_r ?? -Infinity)),
    [rows, horizon]
  );

  const baseline = baselines.find((b) => b.horizon === horizon);

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

          {baseline && (
            <div className="verdict">
              <span className="verdict-count tabular">
                {baseline.avg_r == null
                  ? '—'
                  : `${baseline.avg_r > 0 ? '+' : ''}${baseline.avg_r.toFixed(2)}R`}
              </span>
              <span className="verdict-label">
                対照群：<strong>全銘柄を無選別に買った</strong>場合の平均
                （{baseline.n_trades.toLocaleString('ja-JP')}件、勝率 {pct(baseline.win_rate)}）
              </span>
              <p className="verdict-note">
                この期間は相場が上昇したため、買いのみなら銘柄を選ばなくてもプラスになります。
                テーマが超えるべき基準は0ではなく<strong>この数字</strong>です。
                下表の<strong>選別効果</strong>がそれとの差で、これが正でなければ
                そのテーマは無選別に買うのと比べて何も足していません。
              </p>
            </div>
          )}

          <div className="table-scroll">
            <table className="quotes">
              <thead>
                <tr>
                  <th>テーマ</th>
                  <th className="num">選別効果</th>
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
                  const edge = r.edge_r;
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
                        className={`num tabular ${(edge ?? 0) > 0 ? 'up' : 'down'}`}
                        title="テーマの平均R − 無選別に買った場合の平均R。正なら選別が効いている"
                      >
                        {edge == null ? '—' : `${edge > 0 ? '+' : ''}${edge.toFixed(2)}R`}
                      </td>
                      <td
                        className="num tabular"
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
            <strong>並び順は選別効果（対照群との差）です。</strong>
            平均Rで並べると、上昇相場では「どれだけ相場に乗っていたか」の順になってしまい、
            銘柄選別の巧拙が見えません。
            勝率で並べないのも同じ理由で、勝率70%でも1回0.3Rなら勝率30%で3R取るテーマに負けます。
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
