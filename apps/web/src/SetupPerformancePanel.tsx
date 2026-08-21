import { useEffect, useState } from 'react';
import { fetchSetupPerformance, type SetupEdge } from './api';

/** Below this an average is noise wearing a decimal point. */
const MIN_TRADES_TO_READ = 100;
/** Standard errors an edge must clear to be worth a second look. Not a
 * significance claim — with several Setups compared at once, one crossing
 * this by chance is expected. */
const T_NOTABLE = 2.0;

function r(v: number | null | undefined): string {
  if (v == null) return '—';
  return `${v > 0 ? '+' : ''}${Number(v).toFixed(3)}R`;
}

function pct(v: number | null | undefined): string {
  return v == null ? '—' : `${(Number(v) * 100).toFixed(1)}%`;
}

export function SetupPerformancePanel() {
  const [rows, setRows] = useState<SetupEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSetupPerformance()
      .then((res) => setRows(res.performance))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="muted">読み込み中…</p>;
  if (error) return <p className="status-error">エラー: {error}</p>;
  if (rows.length === 0) {
    return (
      <section className="panel">
        <h2>Setupの検証</h2>
        <p className="muted">
          まだ結果がありません。setup-replay ジョブを実行してください。
        </p>
      </section>
    );
  }

  return (
    <section className="panel">
      <h2>Setupの検証</h2>
      <p className="muted footnote">
        すべて<strong>執行コスト差引後</strong>のRです。並び順・判定は
        <strong>選別効果</strong>（Setup − 無選別に全銘柄を買った場合）で見ます。
        検証期間は上昇相場なので、買いのみなら銘柄を選ばなくても総Rはプラスになります。
        Setupが超えるべき基準は0ではなく対照群です。
      </p>

      <div className="table-scroll">
        <table className="quotes">
          <thead>
            <tr>
              <th>Setup</th>
              <th className="num">選別効果</th>
              <th className="num">t値</th>
              <th className="num">純R</th>
              <th className="num">総R</th>
              <th className="num">コスト</th>
              <th className="num">エントリー滑り</th>
              <th className="num">損切幅</th>
              <th className="num">対照群(純)</th>
              <th className="num">取引数</th>
              <th className="num">勝率</th>
              <th className="num">不成立</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => {
              const notable = Math.abs(s.t_stat ?? 0) >= T_NOTABLE;
              const thin = s.n_trades < MIN_TRADES_TO_READ;
              const unreadable = !notable || thin;
              return (
                <tr key={s.setup_key}>
                  <td>
                    {s.setup_name}
                    <span className="theme-kind">{s.horizon === 'day' ? 'デイ' : 'スイング'}</span>
                    {thin && <span className="theme-kind">件数不足</span>}
                  </td>
                  <td
                    className={`num tabular ${unreadable ? 'muted' : (s.edge_r ?? 0) > 0 ? 'up' : 'down'}`}
                    title={
                      unreadable
                        ? 'ばらつきの範囲内。差はあるが偶然と区別できない'
                        : 'Setupの純R − 無選別に買った場合の純R'
                    }
                  >
                    {r(s.edge_r)}
                  </td>
                  <td className={`num tabular ${notable ? '' : 'muted'}`}>
                    {s.t_stat == null ? '—' : Number(s.t_stat).toFixed(2)}
                    {!notable && ' 〓'}
                  </td>
                  <td className={`num tabular ${(s.avg_r ?? 0) > 0 ? 'up' : 'down'}`}>
                    {r(s.avg_r)}
                  </td>
                  <td className="num tabular muted">{r(s.gross_avg_r)}</td>
                  <td
                    className="num tabular down"
                    title="往復のスリッページ・手数料をRで表したもの"
                  >
                    {s.avg_cost_r == null ? '—' : `−${Number(s.avg_cost_r).toFixed(3)}R`}
                  </td>
                  <td
                    className="num tabular down"
                    title="トリガー価格に対して実際にいくら高く約定したか。手数料でもスプレッドでもなく、入り方そのもののコスト"
                  >
                    {s.avg_entry_slip_r == null
                      ? '—'
                      : `−${Number(s.avg_entry_slip_r).toFixed(3)}R`}
                  </td>
                  <td
                    className="num tabular muted"
                    title="損切りをATRの何倍に置いているか。狭いほどR単位のコストが膨らむ"
                  >
                    {s.stop_atr_mult == null ? '—' : `${Number(s.stop_atr_mult).toFixed(1)}×`}
                  </td>
                  <td className="num tabular muted">{r(s.baseline_avg_r)}</td>
                  <td className="num tabular">{s.n_trades.toLocaleString('ja-JP')}</td>
                  <td className="num tabular">{pct(s.win_rate)}</td>
                  <td
                    className="num tabular muted"
                    title="トリガー未到達で期限切れ・反証成立・窓開けで建てられず"
                  >
                    {(s.n_expired + s.n_invalidated + s.n_no_entry).toLocaleString('ja-JP')}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="muted footnote">
        <strong>損切りを狭くするとコストがR単位で膨らみます。</strong>
        スリッページの単価は概ね ATR に比例するため価格に依存せず、往復コストは
        <code> 2 × 0.10 ÷ 損切り倍率 </code>に収束します。損切り1.0×ATRなら約0.20R、
        1.8×ATRなら約0.11R。<strong>同じ執行品質でも、損切りが狭いだけでコストは倍近くになります。</strong>
        「損切りを浅くしてリスクを抑える」は、R単位では逆効果になり得ます。
      </p>

      <p className="muted footnote">
        <strong>ただし最大の費目は往復コストではなく、エントリー滑りです。</strong>
        「終値がXを超えたら翌日の寄りで買う」という入り方は、実測で平均
        0.3〜0.4R 高い値段で約定しています。スプレッドでも手数料でもなく、
        入り方そのものが払っているコストで、往復コスト（0.10〜0.18R）より大きい。
        <strong>手数料の安い証券会社に移しても、ここは1円も改善しません。</strong>
        改善するとすれば、指値で入る・トリガーを翌日の寄りに賭けない、といった
        執行方法の変更だけです。なお純Rにはこの滑りが既に含まれています
        （Rは実約定値から測っているため）——今まで表示していなかっただけです。
      </p>

      <p className="muted footnote">
        <strong>「不成立」はSetupを運用するコストです。</strong>
        候補に出てもトリガーに到達せず期限切れになったもの、反証が先に成立したもの、
        翌寄りが既に損切り水準を割っていて建てられなかったものの合計。
        取引できなかった分は平均Rの分母に入りませんが、件数は「この手法で何回空振りするか」を表します。
      </p>
      <p className="muted footnote">
        <strong>t値が2未満（〓）の行は、差はあっても偶然と区別できません。</strong>
        しかもこのt値は<strong>上限であって下限ではありません</strong>：
        サンプリング間隔に対し保有期間が長いため取引が重なって実効サンプル数は件数より少なく、
        さらに複数Setupを同時に比較しているので、全て無力でも|t|&gt;2が偶然出ることがあります。
        <strong>まだ検証期間と、Setupを設計するときに見ていた期間が同じです。</strong>
        将来も同じ成績が出る証拠ではありません。
      </p>
    </section>
  );
}
