import { useEffect, useState } from 'react';
import { addPositionEvent, closePosition, fetchPositions, type Position } from './api';
import { Modal } from './Modal';

function yen(v: number | string | null | undefined): string {
  if (v == null) return '—';
  return Number(v).toLocaleString('ja-JP', { maximumFractionDigits: 1 });
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

const ADHERENCE_OPTIONS: { value: string; label: string }[] = [
  { value: 'as_planned', label: '計画どおり' },
  { value: 'entered_early', label: '早めに入った' },
  { value: 'entered_late', label: '遅れて入った' },
  { value: 'stop_moved_against_plan', label: '損切りを不利方向に動かした' },
  { value: 'exited_early', label: '早めに手仕舞った' },
  { value: 'exited_late', label: '遅れて手仕舞った' },
  { value: 'size_deviated', label: '株数が計画と違った' },
];

const EXIT_REASONS: { value: string; label: string }[] = [
  { value: 'target', label: '目標到達' },
  { value: 'stop', label: '損切り' },
  { value: 'time_stop', label: '保有期限' },
  { value: 'invalidation', label: '反証成立' },
  { value: 'discretionary', label: '裁量判断' },
  { value: 'regime_change', label: '環境変化' },
];

export function PositionDetailModal({
  positionId,
  onClose,
  onChanged,
}: {
  positionId: number;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [position, setPosition] = useState<Position | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [mode, setMode] = useState<'view' | 'stop' | 'close'>('view');

  const [newStop, setNewStop] = useState('');
  const [stopNote, setStopNote] = useState('');

  const [exitPrice, setExitPrice] = useState('');
  const [exitReason, setExitReason] = useState('target');
  const [thesisWasCorrect, setThesisWasCorrect] = useState(true);
  const [adherence, setAdherence] = useState('as_planned');
  const [reviewNote, setReviewNote] = useState('');

  const load = () => {
    setLoading(true);
    fetchPositions()
      .then((r) => {
        const p = r.positions.find((x) => x.id === positionId);
        if (!p) throw new Error('position not found');
        setPosition(p);
        setNewStop(p.stop_current);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(load, [positionId]);

  const submitStopMove = async () => {
    setSaving(true);
    setError(null);
    try {
      await addPositionEvent(positionId, {
        occurred_on: todayISO(),
        event_type: 'stop_moved',
        price: Number(newStop),
        note: stopNote || undefined,
        new_stop: Number(newStop),
      });
      onChanged();
      setMode('view');
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const submitClose = async () => {
    if (!exitPrice) {
      setError('決済価格を入力してください。');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await closePosition(positionId, {
        closed_on: todayISO(),
        exit_price: Number(exitPrice),
        exit_reason: exitReason,
        thesis_was_correct: thesisWasCorrect,
        execution_adherence: adherence,
        review_note: reviewNote || undefined,
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
  if (!position) {
    return (
      <Modal title="エラー" onClose={onClose}>
        <p className="status-error">{error ?? '見つかりません'}</p>
      </Modal>
    );
  }

  return (
    <Modal title={`${position.ticker4} ${position.security_name ?? ''}`} onClose={onClose}>
      <div className="plan-detail">
        <div className="level-grid">
          <div>
            <span className="level-label">建値</span>
            <span className="tabular">{yen(position.entry_price)}</span>
          </div>
          <div>
            <span className="level-label">株数</span>
            <span className="tabular">{position.shares.toLocaleString('ja-JP')}</span>
          </div>
          <div>
            <span className="level-label">現在値</span>
            <span className="tabular">{yen(position.current_price)}</span>
          </div>
          <div>
            <span className="level-label">現在の損切り</span>
            <span className="tabular down">{yen(position.stop_current)}</span>
          </div>
          <div>
            <span className="level-label">目標</span>
            <span className="tabular up">{yen(position.target_current)}</span>
          </div>
          <div>
            <span className="level-label">現在R</span>
            <span className={`tabular ${Number(position.current_r ?? 0) >= 0 ? 'up' : 'down'}`}>
              {position.current_r == null ? '—' : `${Number(position.current_r) >= 0 ? '+' : ''}${Number(position.current_r).toFixed(2)}R`}
            </span>
          </div>
          <div>
            <span className="level-label">保有期限</span>
            <span className="tabular">{position.time_stop_on}</span>
          </div>
        </div>

        {position.status === 'closed' ? (
          <div className="notice">
            <p>
              <strong>決済済み</strong>（{position.closed_on} / {position.exit_reason}）
              損益 {yen(position.pnl_yen)}円
            </p>
          </div>
        ) : (
          mode === 'view' && (
            <div className="decide-buttons">
              <button className="decide-btn decide-buy" onClick={() => setMode('stop')}>
                損切りを動かす
              </button>
              <button className="decide-btn decide-pass" onClick={() => setMode('close')}>
                決済する
              </button>
            </div>
          )
        )}

        {mode === 'stop' && (
          <div className="decide-block">
            <label className="field-block">
              新しい損切り価格
              <input
                className="search tabular"
                type="number"
                value={newStop}
                onChange={(e) => setNewStop(e.target.value)}
              />
            </label>
            <label className="field-block">
              メモ（任意）
              <input className="search" value={stopNote} onChange={(e) => setStopNote(e.target.value)} />
            </label>
            <div className="decide-buttons">
              <button className="decide-btn decide-buy" disabled={saving} onClick={submitStopMove}>
                更新
              </button>
              <button className="link-btn" onClick={() => setMode('view')}>
                キャンセル
              </button>
            </div>
          </div>
        )}

        {mode === 'close' && (
          <div className="decide-block">
            <label className="field-block">
              決済価格
              <input
                className="search tabular"
                type="number"
                value={exitPrice}
                onChange={(e) => setExitPrice(e.target.value)}
              />
            </label>
            <label className="field-block">
              決済理由
              <select className="select" value={exitReason} onChange={(e) => setExitReason(e.target.value)}>
                {EXIT_REASONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field-block">
              <input
                type="checkbox"
                checked={thesisWasCorrect}
                onChange={(e) => setThesisWasCorrect(e.target.checked)}
              />{' '}
              仮説は正しかった
            </label>
            <label className="field-block">
              執行の遵守
              <select className="select" value={adherence} onChange={(e) => setAdherence(e.target.value)}>
                {ADHERENCE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field-block">
              振り返りメモ
              <textarea
                className="textarea"
                rows={3}
                value={reviewNote}
                onChange={(e) => setReviewNote(e.target.value)}
              />
            </label>
            <p className="muted footnote">
              「勝ったが計画から逸脱した」取引と「負けたが計画どおりだった」取引を区別するための記録です。
              損益だけでは執行の質は分かりません。
            </p>
            <div className="decide-buttons">
              <button className="decide-btn decide-pass" disabled={saving} onClick={submitClose}>
                決済を確定
              </button>
              <button className="link-btn" onClick={() => setMode('view')}>
                キャンセル
              </button>
            </div>
          </div>
        )}

        {error && <p className="status-error">{error}</p>}
      </div>
    </Modal>
  );
}
