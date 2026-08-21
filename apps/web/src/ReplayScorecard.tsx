import { useEffect, useState } from 'react';
import { fetchReplayScorecard, type ScorecardRow } from './api';

const COHORT: Record<string, { label: string; note: string }> = {
  your_buy: { label: 'あなたのBUY', note: 'あなたが「買う」と判断した銘柄だけ' },
  mechanical: { label: '全候補を採用', note: 'その日の候補を選ばず全部買った場合' },
  baseline: { label: '無選別', note: '取引可能な全銘柄を買った場合' },
};

const ORDER = ['your_buy', 'mechanical', 'baseline'];

function r(v: number | null | undefined): string {
  if (v == null) return '—';
  return `${Number(v) > 0 ? '+' : ''}${Number(v).toFixed(3)}R`;
}

export function ReplayScorecard() {
  const [rows, setRows] = useState<ScorecardRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchReplayScorecard()
      .then((res) => setRows(res.scorecard))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading || error) return null;

  const byCohort = new Map(rows.map((x) => [x.cohort, x]));
  const you = byCohort.get('your_buy');
  if (!you || you.n_trades === 0) {
    return (
      <div className="notice">
        <p>
          答え合わせを終えたセッションが貯まると、ここに
          <strong>「あなたのBUY判断」「全候補を採用」「無選別」</strong>の3者比較が出ます。
          3つ必要なのは、あなたのBUYが無選別を上回っても、
          全候補採用が同じだけ上回っているなら、それはSetupの手柄であって
          あなたの選別ではないからです。
        </p>
      </div>
    );
  }

  const mech = byCohort.get('mechanical');
  const base = byCohort.get('baseline');
  const vsMechanical =
    you.avg_r != null && mech?.avg_r != null ? Number(you.avg_r) - Number(mech.avg_r) : null;

  return (
    <div className="panel" style={{ marginBottom: 20 }}>
      <h3 style={{ marginTop: 0 }}>これまでのリプレイ成績</h3>

      <div className="table-scroll">
        <table className="quotes">
          <thead>
            <tr>
              <th>比較対象</th>
              <th className="num">平均R</th>
              <th className="num">勝率</th>
              <th className="num">件数</th>
            </tr>
          </thead>
          <tbody>
            {ORDER.map((key) => {
              const row = byCohort.get(key as ScorecardRow['cohort']);
              if (!row) return null;
              const isYou = key === 'your_buy';
              return (
                <tr key={key}>
                  <td className={isYou ? '' : 'muted'}>
                    <strong>{COHORT[key].label}</strong>
                    <br />
                    <span className="reasons">{COHORT[key].note}</span>
                  </td>
                  <td className={`num tabular ${isYou ? (Number(row.avg_r) > 0 ? 'up' : 'down') : 'muted'}`}>
                    {r(row.avg_r)}
                  </td>
                  <td className="num tabular muted">
                    {row.win_rate == null ? '—' : `${(Number(row.win_rate) * 100).toFixed(1)}%`}
                  </td>
                  <td className="num tabular muted">{row.n_trades.toLocaleString('ja-JP')}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="muted footnote">
        {vsMechanical != null && (
          <>
            あなたの選別は全候補採用に対して{' '}
            <strong className={vsMechanical > 0 ? 'up' : 'down'}>{r(vsMechanical)}</strong>。
            これが正なら「候補の中から選ぶ」ことに価値があったことになります。{' '}
          </>
        )}
        ただし<strong>{you.n_trades}件では何も判定できません。</strong>
        1取引あたりRのばらつきは標準偏差で1以上あるので、
        0.1R程度の差を偶然と区別するには数百〜千件単位が必要です。
        {base?.avg_r != null && (
          <>
            {' '}無選別でも {r(base.avg_r)} 出ているのは、検証期間が上昇相場だったためです。
          </>
        )}
      </p>
    </div>
  );
}
