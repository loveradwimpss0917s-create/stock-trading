import { useEffect, useState } from 'react';
import { fetchDiscipline, type DisciplineSummary, type PositionBehaviour } from './api';

/**
 * The discipline audit.
 *
 * Deliberately says nothing about whether any Setup works. It reports what
 * was done relative to the plan that was written before the trade — which
 * is arithmetic about the past, so it is correct today with no edge
 * established and none assumed.
 *
 * The distinction the whole panel turns on: a trade that followed the plan
 * and lost carries no flag; a trade that broke the plan and won does. Any
 * discipline measure scored on P&L collapses, because the market pays out
 * on bad process often enough to keep it alive.
 */

const FLAG_LABEL: Record<keyof typeof FLAG_HELP, string> = {
  stop_widened: 'ストップを不利方向に動かした',
  held_past_time_stop: 'タイムストップ超過で保有継続',
  cut_a_winner_short: '伸びていた利益を早く切った',
  rode_past_the_stop: 'ストップ超過の逆行を保有',
  overrode_a_pass: 'PASS判定を覆して建玉',
  no_recorded_decision: '判断記録なしで建玉',
};

const FLAG_HELP = {
  stop_widened:
    '最も損害が大きい破り方。その瞬間には「まだ戻る」という筋の通った説明がつくので、後から気づけない。',
  held_past_time_stop:
    '想定した期間に想定した動きが出なかった時点で、仮説は外れている。値動きが無いことは中立ではない。',
  cut_a_winner_short:
    '最大順行の半分未満で裁量手仕舞いしたもの。少数の大きな勝ちが期待値の全部を作るので、これは直接その源泉を削る。',
  rode_past_the_stop:
    'ストップ幅を1.2R超えて逆行したまま持っていた。窓開けなら無実だが、そうでなければストップは執行されていない。',
  overrode_a_pass:
    '最終判断は人間が持つので禁止ではない。ただし覆した回数と、その結果は記録される。',
  no_recorded_decision:
    '理由の無いトレードは後から検証できない。良かったのか運が良かったのかを永久に区別できなくなる。',
} as const;

type FlagKey = keyof typeof FLAG_HELP;
const FLAG_KEYS = Object.keys(FLAG_HELP) as FlagKey[];

const SUMMARY_COUNT: Record<FlagKey, keyof DisciplineSummary> = {
  stop_widened: 'n_stop_widened',
  held_past_time_stop: 'n_held_past_time_stop',
  cut_a_winner_short: 'n_cut_short',
  rode_past_the_stop: 'n_rode_past_stop',
  overrode_a_pass: 'n_overrode_pass',
  no_recorded_decision: 'n_no_decision',
};

export function DisciplinePanel() {
  const [summary, setSummary] = useState<DisciplineSummary | null>(null);
  const [positions, setPositions] = useState<PositionBehaviour[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDiscipline()
      .then((r) => {
        setSummary(r.summary);
        setPositions(r.positions);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <section className="panel"><p className="muted">読み込み中…</p></section>;
  if (error) return <section className="panel"><p className="status-error">エラー: {error}</p></section>;

  const flagged = positions.filter((p) => FLAG_KEYS.some((k) => p[k]));
  const adherence = summary?.plan_adherence_rate;
  const holdGap =
    summary?.avg_hold_winners != null && summary?.avg_hold_losers != null
      ? summary.avg_hold_losers - summary.avg_hold_winners
      : null;

  return (
    <section className="panel">
      <h2>規律の記録</h2>
      <p className="muted footnote">
        <strong>計画どおりに実行して負けたトレードには、印は付きません。</strong>
        計画を破って勝ったトレードには付きます。損益で規律を測ると必ず壊れるためです
        — 相場は、悪い手順にも十分な頻度で報酬を払ってしまいます。
      </p>

      {!summary || summary.n_positions === 0 ? (
        <p className="notice">
          建玉の記録がまだありません。この画面は、あなたが実際に建てて閉じたトレードだけを
          材料にします。<strong>予測を一切含まないので、銘柄選択に価値が見つかるかどうかとは
          無関係に、最初のトレードから正しく動きます。</strong>
        </p>
      ) : (
        <>
          <div className="stat-row">
            <div className="stat">
              <span className="stat-label">計画遵守率</span>
              <span className={`stat-value tabular ${adherence != null && adherence < 0.8 ? 'down' : ''}`}>
                {adherence != null ? `${(adherence * 100).toFixed(0)}%` : '—'}
              </span>
            </div>
            <div className="stat">
              <span className="stat-label">決済済み</span>
              <span className="stat-value tabular">{summary.n_closed}件</span>
            </div>
            <div className="stat">
              <span className="stat-label">勝ちの平均保有</span>
              <span className="stat-value tabular">
                {summary.avg_hold_winners != null ? `${summary.avg_hold_winners}日` : '—'}
              </span>
            </div>
            <div className="stat">
              <span className="stat-label">負けの平均保有</span>
              <span className={`stat-value tabular ${holdGap != null && holdGap > 0 ? 'down' : ''}`}>
                {summary.avg_hold_losers != null ? `${summary.avg_hold_losers}日` : '—'}
              </span>
            </div>
            <div className="stat">
              <span className="stat-label">負け直後の増量</span>
              <span className={`stat-value tabular ${summary.n_sized_up_after_loss > 0 ? 'down' : ''}`}>
                {summary.n_sized_up_after_loss}回
              </span>
            </div>
          </div>

          {holdGap != null && holdGap > 0 && (
            <p className="muted footnote">
              <strong>負けを勝ちより {holdGap.toFixed(1)}日 長く持っています。</strong>
              これは相場観の問題ではありません。含み損は確定しなければ損ではない、という
              感覚だけで説明がつく現象で（disposition effect）、しかも本人には
              「もう少しで戻る」としか見えません。順序が逆——勝ちを長く、負けを短く——
              になるまでは、期待値がプラスでも取りこぼし続けます。
            </p>
          )}

          {summary.n_sized_up_after_loss > 0 && (
            <p className="muted footnote">
              <strong>負けた直後にリスクを増やした回数が {summary.n_sized_up_after_loss} 回あります。</strong>
              最も再現性のある破産経路です。「リスク計算」タブで、同じ期待値のまま
              賭け金だけを上げると破産確率がどう跳ねるかを確認してください。
            </p>
          )}

          <h3>破りの内訳</h3>
          <div className="gate-list">
            {FLAG_KEYS.map((key) => {
              const n = Number(summary[SUMMARY_COUNT[key]] ?? 0);
              return (
                <div key={key} className={`gate-row ${n === 0 ? 'gate-pass' : 'gate-fail'}`}>
                  <span className="gate-icon">{n === 0 ? '✓' : '✗'}</span>
                  <span className="gate-name">
                    {FLAG_LABEL[key]}
                    <span className="muted footnote"> {FLAG_HELP[key]}</span>
                  </span>
                  <span className="gate-value tabular">{n}件</span>
                </div>
              );
            })}
          </div>

          {flagged.length > 0 && (
            <>
              <h3>該当したトレード</h3>
              <div className="table-scroll">
                <table className="quotes">
                  <thead>
                    <tr>
                      <th>建玉日</th>
                      <th>銘柄</th>
                      <th>Setup</th>
                      <th className="num">R</th>
                      <th>破り</th>
                    </tr>
                  </thead>
                  <tbody>
                    {flagged.map((p) => (
                      <tr key={p.position_id}>
                        <td className="tabular">{p.opened_on}</td>
                        <td className="tabular">{p.code}</td>
                        <td>{p.setup_key}</td>
                        <td className={`num tabular ${Number(p.r_multiple) < 0 ? 'down' : 'up'}`}>
                          {p.r_multiple != null ? Number(p.r_multiple).toFixed(2) : '—'}
                        </td>
                        <td>
                          {FLAG_KEYS.filter((k) => p[k]).map((k) => (
                            <span key={k} className="badge">{FLAG_LABEL[k]}</span>
                          ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}

      <p className="muted footnote">
        この画面はあなたを採点するためのものではなく、
        <strong>次に同じことをする前に思い出すためのものです。</strong>
        破りは、その瞬間には必ず筋の通った理由を伴って現れます。事後に数えるしか
        方法がないのはそのためです。
      </p>
    </section>
  );
}
