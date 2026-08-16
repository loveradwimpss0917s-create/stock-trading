import { useEffect, useMemo, useState } from 'react';
import { fetchJournal, type Position } from './api';

interface JournalRow extends Position {
  journal: {
    thesis_was_correct: boolean | null;
    execution_adherence: string | null;
    review_note: string | null;
  } | null;
}

function yen(v: number | string | null | undefined): string {
  if (v == null) return '—';
  return Number(v).toLocaleString('ja-JP', { maximumFractionDigits: 1 });
}

type Quadrant = 'right_win' | 'lucky_win' | 'right_loss' | 'bad_loss' | 'unreviewed';

const QUADRANT_LABEL: Record<Quadrant, string> = {
  right_win: '正しい勝ち',
  lucky_win: '危険な勝ち',
  right_loss: '正しい負け',
  bad_loss: '悪い負け',
  unreviewed: '未振り返り',
};

function classify(row: JournalRow): Quadrant {
  if (!row.journal || row.journal.execution_adherence == null) return 'unreviewed';
  const won = Number(row.r_multiple ?? 0) > 0;
  const asPlanned = row.journal.execution_adherence === 'as_planned';
  if (won && asPlanned) return 'right_win';
  if (won && !asPlanned) return 'lucky_win';
  if (!won && asPlanned) return 'right_loss';
  return 'bad_loss';
}

export function JournalPanel() {
  const [rows, setRows] = useState<JournalRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Quadrant | ''>('');

  useEffect(() => {
    fetchJournal()
      .then((r) => setRows(r.journal as JournalRow[]))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  const counts = useMemo(() => {
    const c: Record<Quadrant, number> = {
      right_win: 0, lucky_win: 0, right_loss: 0, bad_loss: 0, unreviewed: 0,
    };
    for (const r of rows) c[classify(r)]++;
    return c;
  }, [rows]);

  const visible = filter ? rows.filter((r) => classify(r) === filter) : rows;

  return (
    <section className="panel">
      <h2>トレードジャーナル</h2>
      <p className="muted footnote">
        損益だけでなく、<strong>計画どおりに執行できたか</strong>で分類します。
        「勝ったが計画から逸脱した」取引は次も勝てる保証がなく、「負けたが計画どおりだった」取引はコストであって改善対象ではありません。
      </p>

      <div className="quadrant-grid">
        {(['right_win', 'lucky_win', 'right_loss', 'bad_loss'] as const).map((q) => (
          <button
            key={q}
            className={`quadrant-card quadrant-${q}${filter === q ? ' is-active' : ''}`}
            onClick={() => setFilter(filter === q ? '' : q)}
          >
            <span className="quadrant-count tabular">{counts[q]}</span>
            <span className="quadrant-label">{QUADRANT_LABEL[q]}</span>
          </button>
        ))}
      </div>
      {counts.unreviewed > 0 && (
        <p className="muted">
          未振り返り: {counts.unreviewed}件（決済時の振り返り入力が未完了です）
        </p>
      )}

      {error && <p className="status-error">{error}</p>}
      {loading && <p className="muted">読み込み中…</p>}
      {!loading && visible.length === 0 && <p className="muted">該当する記録はありません。</p>}

      {visible.length > 0 && (
        <div className="table-scroll">
          <table className="quotes">
            <thead>
              <tr>
                <th>決済日</th>
                <th>銘柄</th>
                <th className="num">R</th>
                <th className="num">損益(円)</th>
                <th>分類</th>
                <th>執行</th>
                <th>メモ</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => (
                <tr key={r.id}>
                  <td className="tabular">{r.closed_on}</td>
                  <td>
                    <span className="tabular code">{r.ticker4}</span> {r.security_name}
                  </td>
                  <td className={`num tabular ${Number(r.r_multiple ?? 0) >= 0 ? 'up' : 'down'}`}>
                    {r.r_multiple == null ? '—' : `${Number(r.r_multiple) >= 0 ? '+' : ''}${Number(r.r_multiple).toFixed(2)}R`}
                  </td>
                  <td className={`num tabular ${Number(r.pnl_yen ?? 0) >= 0 ? 'up' : 'down'}`}>{yen(r.pnl_yen)}</td>
                  <td>
                    <span className={`pill quadrant-pill-${classify(r)}`}>{QUADRANT_LABEL[classify(r)]}</span>
                  </td>
                  <td className="muted">{r.journal?.execution_adherence ?? '—'}</td>
                  <td className="muted">{r.journal?.review_note ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
