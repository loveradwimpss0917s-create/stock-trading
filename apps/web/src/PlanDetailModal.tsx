import { useEffect, useState } from 'react';
import {
  createPosition,
  decidePlan,
  fetchPlan,
  fetchPlanRisk,
  updatePlan,
  type GateResult,
  type RiskVerdict,
  type TradePlan,
} from './api';
import { Modal } from './Modal';

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

const GATE_LABEL: Record<string, string> = {
  min_rr: 'リスクリワード比',
  lot_size: '単元株数',
  notional: '投下資金',
  turnover: '売買代金',
  liquidity: '流動性(対ADV)',
  heat: 'Portfolio heat',
  max_positions: '同時建玉数',
  sector_concentration: 'セクター集中',
};

const DECISION_LABEL: Record<'BUY' | 'WAIT' | 'PASS', string> = {
  BUY: '買う',
  WAIT: '待つ',
  PASS: '見送る',
};

function yen(v: number | string | null | undefined): string {
  if (v == null) return '—';
  return Number(v).toLocaleString('ja-JP', { maximumFractionDigits: 1 });
}

function GateRow({ name, gate }: { name: string; gate: GateResult }) {
  return (
    <div className={`gate-row ${gate.passed ? 'gate-pass' : 'gate-fail'}`}>
      <span className="gate-icon">{gate.passed ? '✓' : '✗'}</span>
      <span className="gate-name">{GATE_LABEL[name] ?? name}</span>
      <span className="gate-value tabular">
        {gate.value == null ? '—' : gate.value}
        {gate.threshold != null && <span className="muted"> / 基準 {gate.threshold}</span>}
      </span>
    </div>
  );
}

export function PlanDetailModal({ planId, onClose, onChanged }: { planId: number; onClose: () => void; onChanged: () => void }) {
  const [plan, setPlan] = useState<TradePlan | null>(null);
  const [verdict, setVerdict] = useState<RiskVerdict | null>(null);
  const [thesis, setThesis] = useState('');
  const [antiThesis, setAntiThesis] = useState('');
  const [scenarios, setScenarios] = useState({ bull: '', base: '', bear: '' });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reasonCode, setReasonCode] = useState('');
  const [reasonNote, setReasonNote] = useState('');
  const [pendingDecision, setPendingDecision] = useState<'BUY' | 'WAIT' | 'PASS' | null>(null);
  const [entryPrice, setEntryPrice] = useState('');
  const [entryShares, setEntryShares] = useState('');

  useEffect(() => {
    setLoading(true);
    // Fetched together regardless of state — cheap, and avoids a stale
    // closure on `plan` inside its own loader. The verdict is simply not
    // rendered for a non-draft plan.
    Promise.all([fetchPlan(planId), fetchPlanRisk(planId)])
      .then(([p, v]) => {
        setPlan(p);
        setThesis(p.thesis ?? '');
        setAntiThesis(p.anti_thesis ?? '');
        const s = (p.scenarios ?? {}) as { bull?: string; base?: string; bear?: string };
        setScenarios({ bull: s.bull ?? '', base: s.base ?? '', bear: s.bear ?? '' });
        setVerdict(v);
        setReasonCode(v.reasonCode);
        if (p.state === 'triggered') {
          setEntryPrice(p.triggered_price ?? p.trigger_price);
          setEntryShares(String(p.shares_planned ?? v.shares));
        }
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [planId]);

  const saveThesis = async () => {
    setSaving(true);
    setError(null);
    try {
      await updatePlan(planId, { thesis, anti_thesis: antiThesis, scenarios });
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const submitDecision = async (decision: 'BUY' | 'WAIT' | 'PASS') => {
    if (decision !== 'PASS' && !thesis.trim()) {
      setError('BUY/WAIT には仮説（thesis）の記入が必要です。');
      return;
    }
    if (!reasonCode.trim()) {
      setError('理由を入力してください。');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      // Persist the thesis first — decide requires it to already be saved.
      if (decision !== 'PASS') {
        await updatePlan(planId, { thesis, anti_thesis: antiThesis, scenarios });
      }
      await decidePlan(planId, { decision, reason_code: reasonCode, reason_note: reasonNote || undefined });
      onChanged();
      onClose();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
      setPendingDecision(null);
    }
  };

  const submitEntry = async () => {
    if (!entryPrice || !entryShares) {
      setError('約定価格と株数を入力してください。');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createPosition({
        plan_id: planId,
        opened_on: todayISO(),
        entry_price: Number(entryPrice),
        shares: Number(entryShares),
      });
      onChanged();
      onClose();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <Modal title="読み込み中…" onClose={onClose}>
        <p className="muted">読み込み中…</p>
      </Modal>
    );
  }
  if (!plan) {
    return (
      <Modal title="エラー" onClose={onClose}>
        <p className="status-error">{error ?? '見つかりません'}</p>
      </Modal>
    );
  }

  const isDraft = plan.state === 'draft';

  return (
    <Modal title={`${plan.ticker4} ${plan.security_name ?? ''}`} onClose={onClose}>
      <div className="plan-detail">
        <div className="plan-meta-row">
          <span className="pill">{plan.setup_name}</span>
          <span className="pill">{plan.setup_horizon === 'day' ? 'デイ' : 'スイング'}</span>
          <span className={`pill state-${plan.state}`}>{plan.state}</span>
        </div>
        <p className="muted setup-hypothesis">{plan.setup_hypothesis}</p>

        <div className="level-grid">
          <div>
            <span className="level-label">基準終値</span>
            <span className="tabular">{yen(plan.reference_close)}</span>
          </div>
          <div>
            <span className="level-label">トリガー</span>
            <span className="tabular up">{yen(plan.trigger_price)}</span>
          </div>
          <div>
            <span className="level-label">損切り</span>
            <span className="tabular down">{yen(plan.stop_planned)}</span>
          </div>
          <div>
            <span className="level-label">目標</span>
            <span className="tabular up">{yen(plan.target_planned)}</span>
          </div>
          <div>
            <span className="level-label">反証水準</span>
            <span className="tabular">{yen(plan.invalidation?.level)}</span>
          </div>
          <div>
            <span className="level-label">期待R:R</span>
            <span className="tabular">{Number(plan.expected_rr).toFixed(2)}</span>
          </div>
          <div>
            <span className="level-label">期限</span>
            <span className="tabular">{plan.expires_on}</span>
          </div>
          {plan.current_price && (
            <div>
              <span className="level-label">現在値</span>
              <span className="tabular">{yen(plan.current_price)}</span>
            </div>
          )}
        </div>

        {isDraft ? (
          <>
            <label className="field-block">
              仮説（thesis）— なぜ今この銘柄を見るのか
              <textarea
                className="textarea"
                rows={3}
                value={thesis}
                onChange={(e) => setThesis(e.target.value)}
                placeholder="例：20日高値を出来高を伴って更新。セクター全体も強く、押し目形成後の再加速局面と判断"
              />
            </label>
            <label className="field-block">
              反証材料（anti-thesis）— 何が起きたらこの仮説は間違いか
              <textarea
                className="textarea"
                rows={2}
                value={antiThesis}
                onChange={(e) => setAntiThesis(e.target.value)}
                placeholder="例：出来高が伴っていない場合はダマシの可能性。セクター全体が反落したら要警戒"
              />
            </label>

            <div className="scenario-grid">
              <label className="field-block">
                Bull
                <textarea
                  className="textarea small"
                  rows={2}
                  value={scenarios.bull}
                  onChange={(e) => setScenarios((s) => ({ ...s, bull: e.target.value }))}
                />
              </label>
              <label className="field-block">
                Base
                <textarea
                  className="textarea small"
                  rows={2}
                  value={scenarios.base}
                  onChange={(e) => setScenarios((s) => ({ ...s, base: e.target.value }))}
                />
              </label>
              <label className="field-block">
                Bear
                <textarea
                  className="textarea small"
                  rows={2}
                  value={scenarios.bear}
                  onChange={(e) => setScenarios((s) => ({ ...s, bear: e.target.value }))}
                />
              </label>
            </div>

            <button className="link-btn" onClick={saveThesis} disabled={saving}>
              下書きを保存
            </button>

            {verdict && (
              <div className="risk-verdict-block">
                <h3>Risk Engine 判定</h3>
                <div className={`verdict verdict-${verdict.decision.toLowerCase()}`}>
                  <span className="verdict-count">{DECISION_LABEL[verdict.decision]}</span>
                  <span className="verdict-label">
                    株数 {verdict.shares.toLocaleString('ja-JP')} / リスク額{' '}
                    {yen(verdict.riskAmount)}円 ({(verdict.riskPct * 100).toFixed(2)}%) / R:R{' '}
                    {verdict.rr.toFixed(2)}
                  </span>
                </div>
                <div className="gate-list">
                  {Object.entries(verdict.gates).map(([name, gate]) => (
                    <GateRow key={name} name={name} gate={gate} />
                  ))}
                </div>
                <p className="muted footnote">
                  この判定は機械的なゲート（算術）のみです。買う/待つ/見送るの最終判断はあなたが行い、
                  理由を必ず記録します。
                </p>
              </div>
            )}

            <div className="decide-block">
              <label className="field-block">
                理由コード
                <input
                  className="search"
                  value={reasonCode}
                  onChange={(e) => setReasonCode(e.target.value)}
                  placeholder="例: all_gates_passed / news_risk / sector_overlap"
                />
              </label>
              <label className="field-block">
                補足（任意）
                <input
                  className="search"
                  value={reasonNote}
                  onChange={(e) => setReasonNote(e.target.value)}
                />
              </label>
              <div className="decide-buttons">
                {(['BUY', 'WAIT', 'PASS'] as const).map((d) => (
                  <button
                    key={d}
                    className={`decide-btn decide-${d.toLowerCase()}${pendingDecision === d ? ' is-pending' : ''}`}
                    disabled={saving}
                    onClick={() => {
                      setPendingDecision(d);
                      submitDecision(d);
                    }}
                  >
                    {DECISION_LABEL[d]}
                  </button>
                ))}
              </div>
            </div>
          </>
        ) : (
          <>
            <div className="notice">
              <p>
                {plan.thesis && (
                  <>
                    <strong>仮説：</strong>
                    {plan.thesis}
                    <br />
                  </>
                )}
                {plan.anti_thesis && (
                  <>
                    <strong>反証材料：</strong>
                    {plan.anti_thesis}
                  </>
                )}
              </p>
            </div>

            {plan.state === 'triggered' && (
              <div className="decide-block">
                <h3>約定を記録</h3>
                <p className="muted">
                  {plan.triggered_on} にトリガー到達（終値 {yen(plan.triggered_price)}）。
                  実際に約定した価格・株数を記録してください。
                </p>
                <label className="field-block">
                  約定価格
                  <input
                    className="search tabular"
                    type="number"
                    value={entryPrice}
                    onChange={(e) => setEntryPrice(e.target.value)}
                  />
                </label>
                <label className="field-block">
                  株数
                  <input
                    className="search tabular"
                    type="number"
                    step={100}
                    value={entryShares}
                    onChange={(e) => setEntryShares(e.target.value)}
                  />
                </label>
                <button className="decide-btn decide-buy" disabled={saving} onClick={submitEntry}>
                  約定を記録
                </button>
              </div>
            )}
          </>
        )}

        {error && <p className="status-error">{error}</p>}
      </div>
    </Modal>
  );
}
