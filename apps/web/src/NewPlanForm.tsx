import { useMemo, useState } from 'react';
import { createPlan } from './api';
import { planEconomics } from '@kabu-quant/core';

/**
 * Enter a trade you are actually taking.
 *
 * The form computes and shows R:R, cost and the break-even win rate as you
 * type, before anything is saved. That ordering is the point: the numbers
 * that decide whether a trade is worth taking are available while the
 * levels can still be changed, rather than in a report afterwards.
 *
 * Nothing here predicts. Every figure follows from the three prices.
 */
export function NewPlanForm({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState('');
  const [entry, setEntry] = useState('');
  const [stop, setStop] = useState('');
  const [target, setTarget] = useState('');
  const [atr, setAtr] = useState('');
  const [thesis, setThesis] = useState('');
  const [antiThesis, setAntiThesis] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const nums = {
    entry: Number(entry),
    stop: Number(stop),
    target: Number(target),
    atr: atr.trim() ? Number(atr) : null,
  };

  const econ = useMemo(() => {
    if (![nums.entry, nums.stop, nums.target].every((v) => Number.isFinite(v) && v > 0)) return null;
    return planEconomics(nums.entry, nums.stop, nums.target, nums.atr);
  }, [entry, stop, target, atr]);

  const submit = async () => {
    setError(null);
    setSaving(true);
    try {
      // 4-digit ticker to the 5-digit J-Quants code, which is what the
      // securities table is keyed on.
      const raw = code.trim();
      await createPlan({
        code: raw.length === 4 ? `${raw}0` : raw,
        trigger_price: nums.entry,
        stop_planned: nums.stop,
        target_planned: nums.target,
        atr: nums.atr,
        thesis,
        anti_thesis: antiThesis || undefined,
      });
      setCode(''); setEntry(''); setStop(''); setTarget(''); setAtr('');
      setThesis(''); setAntiThesis('');
      setOpen(false);
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  if (!open) {
    return (
      <button className="link-btn" onClick={() => setOpen(true)}>
        ＋ 自分のトレードを記録する
      </button>
    );
  }

  return (
    <div className="panel new-plan-form">
      <h3>自分のトレードを記録する</h3>
      <p className="muted footnote">
        実際に自分の証券口座で建てる（建てた）トレードを、ここに入れます。
        このアプリの候補である必要はありません。
        <strong>エントリー前にストップを書くことが唯一の必須条件です</strong>
        — 書いていなければRが定義できず、以後どの数字も意味を持ちません。
      </p>

      <div className="filters">
        <label className="field">
          銘柄コード
          <input className="num-input tabular" value={code} placeholder="7203"
                 onChange={(e) => setCode(e.target.value)} />
        </label>
        <label className="field">
          エントリー
          <input className="num-input tabular" inputMode="decimal" value={entry}
                 onChange={(e) => setEntry(e.target.value)} />
        </label>
        <label className="field">
          ストップ
          <input className="num-input tabular" inputMode="decimal" value={stop}
                 onChange={(e) => setStop(e.target.value)} />
        </label>
        <label className="field">
          目標
          <input className="num-input tabular" inputMode="decimal" value={target}
                 onChange={(e) => setTarget(e.target.value)} />
        </label>
        <label className="field">
          ATR(14) 任意
          <input className="num-input tabular" inputMode="decimal" value={atr}
                 onChange={(e) => setAtr(e.target.value)} />
        </label>
      </div>

      {econ && (
        <div className="stat-row">
          <div className="stat">
            <span className="stat-label">R:R（コスト後）</span>
            <span className={`stat-value tabular ${econ.rrNet < 1 ? 'down' : ''}`}>
              {econ.rrNet.toFixed(2)}
            </span>
          </div>
          <div className="stat">
            <span className="stat-label">R:R（コスト前）</span>
            <span className="stat-value tabular">{econ.rrGross.toFixed(2)}</span>
          </div>
          <div className="stat">
            <span className="stat-label">往復コスト</span>
            <span className="stat-value tabular">
              {(econ.costWinR + econ.costLossR).toFixed(3)}R
            </span>
          </div>
          <div className="stat">
            <span className="stat-label">必要勝率</span>
            <span className="stat-value tabular">
              {econ.requiredWinRateNet != null
                ? `${(econ.requiredWinRateNet * 100).toFixed(1)}%`
                : '達成不能'}
            </span>
          </div>
        </div>
      )}

      {econ && !nums.atr && (
        <p className="muted footnote">
          ATRが未入力のため、スリッページは最低値（5bp）で計算しています。
          <strong>実際のコストはこれより大きくなります</strong>
          — つまり上の必要勝率は甘めに出ています。
        </p>
      )}

      <label className="field-block">
        根拠（必須）
        <textarea className="textarea" rows={2} value={thesis}
                  placeholder="なぜ今この銘柄を、この値段で買うのか"
                  onChange={(e) => setThesis(e.target.value)} />
      </label>
      <label className="field-block">
        反証条件（何が起きたらこの根拠は間違いか）
        <textarea className="textarea" rows={2} value={antiThesis}
                  placeholder="書いておくと、後から理由を作り直せなくなります"
                  onChange={(e) => setAntiThesis(e.target.value)} />
      </label>

      {error && <p className="status-error">{error}</p>}

      <div className="row-actions">
        <button className="btn-primary" onClick={submit} disabled={saving || !econ || !thesis.trim()}>
          {saving ? '保存中…' : '記録する'}
        </button>
        <button className="link-btn" onClick={() => setOpen(false)}>やめる</button>
      </div>
    </div>
  );
}
