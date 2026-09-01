import { useState } from 'react';
import {
  decideReplay,
  revealReplay,
  startReplay,
  type ReplayCandidate,
  type ReplayResult,
} from './api';
import { ReplayScorecard } from './ReplayScorecard';

function yen(v: number | string | null | undefined): string {
  if (v == null) return '—';
  return Number(v).toLocaleString('ja-JP', { maximumFractionDigits: 1 });
}

const DECISION_LABEL = { BUY: '買う', WAIT: '待つ', PASS: '見送る' } as const;

// Every outcome walk_plan/evaluate can produce needs a label here. Before
// this fix, 'expired' and 'invalidated' had none — a candidate that simply
// never triggered rendered as a blank "—", indistinguishable from broken
// data. For reversal_3d that is most rows (it fails to trigger ~69% of the
// time), so most replay sessions looked like something was wrong when
// nothing was: the Setup just didn't fire, which is itself the finding.
const OUTCOME_LABEL: Record<string, { text: string; cls: string }> = {
  target: { text: '目標到達', cls: 'up' },
  stop: { text: '損切り', cls: 'down' },
  // Renamed from '期限切れ' — that phrase is now reserved for 'expired'
  // below. This one DID trigger and become a real trade; it just ran out
  // the clock before hitting either barrier. Conflating the two made a
  // trade that happened look identical to one that never did.
  timeout: { text: '保有上限で決済', cls: '' },
  no_entry: { text: '見送り(窓開け)', cls: 'muted' },
  // Never triggered before its entry window ran out. No trade, no R —
  // that absence is the candidate's own result, not missing data.
  expired: { text: '不成立(未発火)', cls: 'muted' },
  // The anti-thesis condition fired before the trigger did.
  invalidated: { text: '反証成立', cls: 'muted' },
};

export function ReplayPanel() {
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<ReplayCandidate[]>([]);
  const [decisions, setDecisions] = useState<Record<string, { decision: string; reason: string }>>({});
  const [results, setResults] = useState<ReplayResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setLoading(true);
    setError(null);
    setResults(null);
    setDecisions({});
    try {
      const r = await startReplay();
      setSessionId(r.session_id);
      setAsOf(r.as_of);
      setCandidates(r.candidates);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const key = (c: ReplayCandidate) => `${c.code}/${c.setup_key}`;

  const decide = async (c: ReplayCandidate, decision: 'BUY' | 'WAIT' | 'PASS') => {
    if (!sessionId) return;
    const reason = decision === 'PASS' ? 'discretionary' : 'discretionary';
    setDecisions((d) => ({ ...d, [key(c)]: { decision, reason } }));
    try {
      await decideReplay(sessionId, { code: c.code, setup_key: c.setup_key, decision, reason_code: reason });
    } catch (e) {
      setError(String(e));
    }
  };

  const reveal = async () => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    try {
      const r = await revealReplay(sessionId);
      setResults(r.results);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const decidedCount = Object.keys(decisions).length;

  return (
    <section className="panel">
      <h2>リプレイ訓練</h2>
      <p className="muted footnote">
        過去のある1日を「今日」として、その日に出ていたはずのSetup候補を見せます。
        結果を見ずにBUY/WAIT/PASSを判断してから、答え合わせをしてください。
        実弾なら年間250回程度しか積めない判断を、まとめて練習できます。
      </p>

      {!sessionId && (
        <>
          <ReplayScorecard />
          <button className="decide-btn decide-buy" onClick={start} disabled={loading}>
            {loading ? '読み込み中…' : 'リプレイを開始'}
          </button>
        </>
      )}

      {error && <p className="status-error">{error}</p>}

      {sessionId && !results && (
        <>
          <div className="asof asof-stale">
            基準日 <span className="tabular">{asOf}</span> — この日の情報だけで判断してください。
            以降の値動きはまだ見せていません。
          </div>

          {candidates.length === 0 ? (
            <p className="muted">この日は条件を満たす候補がありませんでした。</p>
          ) : (
            <div className="table-scroll">
              <table className="quotes">
                <thead>
                  <tr>
                    <th>銘柄</th>
                    <th>Setup</th>
                    <th className="num">トリガー</th>
                    <th className="num">損切り</th>
                    <th className="num">目標</th>
                    <th>判断</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((c) => {
                    const d = decisions[key(c)];
                    return (
                      <tr key={key(c)}>
                        <td>
                          <span className="tabular code">{c.ticker4}</span> {c.security_name}
                        </td>
                        <td className="muted">{c.setup_name}</td>
                        <td className="num tabular">{yen(c.trigger_price)}</td>
                        <td className="num tabular down">{yen(c.stop_planned)}</td>
                        <td className="num tabular up">{yen(c.target_planned)}</td>
                        <td>
                          <div className="decide-buttons">
                            {(['BUY', 'WAIT', 'PASS'] as const).map((opt) => (
                              <button
                                key={opt}
                                className={`decide-btn decide-${opt.toLowerCase()}${d?.decision === opt ? ' is-pending' : ''}`}
                                onClick={() => decide(c, opt)}
                              >
                                {DECISION_LABEL[opt]}
                              </button>
                            ))}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {candidates.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <button
                className="decide-btn decide-pass"
                disabled={decidedCount === 0 || loading}
                onClick={reveal}
              >
                {decidedCount}/{candidates.length}件 判断済み — 答え合わせする
              </button>
            </div>
          )}
        </>
      )}

      {results && (
        <>
          <div className="table-scroll">
            <table className="quotes">
              <thead>
                <tr>
                  <th>銘柄</th>
                  <th>あなたの判断</th>
                  <th>結果</th>
                  <th className="num">R</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => {
                  const label = r.outcome ? OUTCOME_LABEL[r.outcome.outcome] : null;
                  return (
                    <tr key={`${r.code}/${r.setup_key}`}>
                      <td>
                        <span className="tabular code">{r.outcome?.ticker4}</span> {r.outcome?.security_name}
                      </td>
                      <td>
                        <span className={`pill decide-${r.decision.toLowerCase()}`}>
                          {DECISION_LABEL[r.decision]}
                        </span>
                      </td>
                      <td className={label?.cls}>{label?.text ?? '—'}</td>
                      <td className={`num tabular ${Number(r.outcome?.r_multiple ?? 0) >= 0 ? 'up' : 'down'}`}>
                        {r.outcome?.r_multiple == null
                          ? '—'
                          : `${Number(r.outcome.r_multiple) >= 0 ? '+' : ''}${Number(r.outcome.r_multiple).toFixed(2)}R`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="muted footnote">
            <strong>「不成立(未発火)」「反証成立」はRが「—」になりますが、データ欠損ではありません。</strong>
            トリガーに到達しなかった、または反証条件が先に成立した——つまりそもそも取引が発生しなかった、
            ということ自体がその候補の結果です。reversal_3dは実測で約7割がここに入るため、
            1回のセッションで大半が「—」になるのは正常です。買う/待つと判断していても、
            発火しなかった候補は評価しようがありません（勝ちでも負けでもない）。
          </p>
          <p className="muted footnote">
            これは1セッション分の結果です。<strong>1回の答え合わせで「自分に才能がある/ない」は分かりません。</strong>
            何百回と繰り返して初めて、判断の傾向が見えてきます。
          </p>
          <button className="decide-btn decide-buy" onClick={start} style={{ marginTop: 12 }}>
            もう一度
          </button>
        </>
      )}
    </section>
  );
}
