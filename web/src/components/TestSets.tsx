import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { ApiError, del, get, put } from '../api';
import { t, tm } from '../i18n';
import { compareRows } from '../lib/testRuns';
import { useToast } from './Toasts';
import { Dialog } from './ui';

// Chat test sets (#50): a start situation, a persona and inputs saved under a name, run again and compared side by side.

export type TestSet = { id: string; name: string; start: string | null; persona: { name: string; description: string } | null; inputs: string[] };
type Sets = { sets: TestSet[]; revision: string };
type RunSummary = {
  id: string;
  set: { id: string; name: string };
  model: { provider: string; name: string; model: string } | null;
  snapshot: { id: string; created_at?: string; label?: string | null } | null;
  started_at: string;
  status: 'running' | 'done' | 'stopped' | 'error';
  turns: number;
  inputs: number;
};
type Run = Omit<RunSummary, 'turns' | 'inputs'> & { set: TestSet; turns: { input: string; reply: string; error?: string | null }[] };

const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString() : '—');
const modelOf = (run: { model: RunSummary['model'] }) => (run.model ? `${run.model.name} · ${run.model.model}` : '—');

export function TestSetsDialog({
  workId,
  current,
  onRun,
  onClose,
}: {
  workId: string;
  current: { start: string | null; persona: TestSet['persona']; inputs: string[] };
  onRun: (set: TestSet) => void;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const sets = useQuery<Sets>({ queryKey: ['test-sets', workId], queryFn: () => get(`/api/works/${workId}/tests/sets`) });
  const [editing, setEditing] = useState<TestSet | null>(null);
  const [runsOf, setRunsOf] = useState<TestSet | null>(null);
  const fail = (err: unknown) => toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });

  async function store(next: TestSet[]) {
    try {
      qc.setQueryData(['test-sets', workId], await put(`/api/works/${workId}/tests/sets`, { base_revision: sets.data!.revision, sets: next }));
      return true;
    } catch (err) {
      fail(err);
      return false;
    }
  }

  if (runsOf) return <RunsDialog workId={workId} set={runsOf} onClose={() => setRunsOf(null)} />;
  if (editing) {
    return (
      <EditSet
        set={editing}
        onCancel={() => setEditing(null)}
        onSave={async (set) => {
          const list = sets.data?.sets ?? [];
          const next = list.some((s) => s.id === set.id) ? list.map((s) => (s.id === set.id ? set : s)) : [...list, set];
          if (await store(next)) setEditing(null);
        }}
      />
    );
  }
  return (
    <Dialog title={t('tests.title')} onClose={onClose} closeLabel={t('common.close')}>
      <p className="faint small">{t('tests.about')}</p>
      {(sets.data?.sets ?? []).length === 0 && <div className="empty">{t('tests.empty')}</div>}
      {(sets.data?.sets ?? []).map((set) => (
        <div key={set.id} className="list-row" style={{ alignItems: 'flex-start' }}>
          <span className="grow col" style={{ gap: 0 }}>
            <strong>{set.name}</strong>
            <span className="faint small">
              {t('tests.summary', { n: set.inputs.length, start: set.start ?? t('tests.no_start'), persona: set.persona?.name || t('persona.none') })}
            </span>
          </span>
          <button className="primary" onClick={() => onRun(set)}>{t('tests.run')}</button>
          <button onClick={() => setRunsOf(set)}>{t('tests.runs')}</button>
          <button className="ghost" onClick={() => setEditing(set)}>{t('tests.edit')}</button>
          <button
            className="ghost danger"
            onClick={() => confirm(t('tests.delete_confirm', { name: set.name })) && store((sets.data?.sets ?? []).filter((s) => s.id !== set.id))}
          >
            {t('common.delete')}
          </button>
        </div>
      ))}
      <div className="row wrap">
        <button
          disabled={!current.inputs.length}
          title={current.inputs.length ? undefined : t('tests.from_chat_empty')}
          onClick={() => setEditing({ id: '', name: '', start: current.start, persona: current.persona, inputs: current.inputs })}
        >
          {t('tests.from_chat', { n: current.inputs.length })}
        </button>
        <button onClick={() => setEditing({ id: '', name: '', start: current.start, persona: current.persona, inputs: [''] })}>{t('tests.new')}</button>
      </div>
    </Dialog>
  );
}

function EditSet({ set, onSave, onCancel }: { set: TestSet; onSave: (set: TestSet) => void; onCancel: () => void }) {
  const [name, setName] = useState(set.name);
  const [inputs, setInputs] = useState<string[]>(set.inputs.length ? set.inputs : ['']);
  const filled = inputs.filter((x) => x.trim());
  return (
    <Dialog
      title={set.id ? t('tests.edit_title') : t('tests.new_title')}
      onClose={onCancel}
      actions={
        <button className="primary" disabled={!name.trim() || !filled.length} onClick={() => onSave({ ...set, name: name.trim(), inputs: filled })}>
          {t('common.save')}
        </button>
      }
    >
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('tests.name')}</span>
        <input autoFocus value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <span className="faint small">{t('tests.summary', { n: filled.length, start: set.start ?? t('tests.no_start'), persona: set.persona?.name || t('persona.none') })}</span>
      <div className="col" style={{ gap: 4, maxHeight: 360, overflow: 'auto' }}>
        {inputs.map((value, n) => (
          <div key={n} className="row" style={{ alignItems: 'flex-start' }}>
            <span className="faint small" style={{ width: 22 }}>{n + 1}</span>
            <textarea className="grow" rows={2} value={value} onChange={(e) => setInputs(inputs.map((x, i) => (i === n ? e.target.value : x)))} />
            <button className="ghost" aria-label={t('common.delete')} onClick={() => setInputs(inputs.filter((_, i) => i !== n))}>
              ×
            </button>
          </div>
        ))}
      </div>
      <button onClick={() => setInputs([...inputs, ''])}>{t('tests.add_input')}</button>
    </Dialog>
  );
}

function RunsDialog({ workId, set, onClose }: { workId: string; set: TestSet; onClose: () => void }) {
  const qc = useQueryClient();
  const runs = useQuery<RunSummary[]>({ queryKey: ['test-runs', workId, set.id], queryFn: () => get(`/api/works/${workId}/tests/runs?set=${set.id}`) });
  const [picked, setPicked] = useState<string[]>([]);
  const [comparing, setComparing] = useState(false);
  if (comparing && picked.length === 2) return <CompareRuns workId={workId} ids={picked} onClose={() => setComparing(false)} />;
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id].slice(-2)));
  return (
    <Dialog
      title={t('tests.runs_title', { name: set.name })}
      onClose={onClose}
      closeLabel={t('common.close')}
      actions={
        <button className="primary" disabled={picked.length !== 2} onClick={() => setComparing(true)}>
          {t('tests.compare')}
        </button>
      }
    >
      <p className="faint small">{t('tests.pick_two')}</p>
      {(runs.data ?? []).length === 0 && <div className="empty">{t('tests.no_runs')}</div>}
      {(runs.data ?? []).map((run) => (
        <label key={run.id} className="row list-row" style={{ flexDirection: 'row', alignItems: 'flex-start' }}>
          <input type="checkbox" checked={picked.includes(run.id)} onChange={() => toggle(run.id)} />
          <span className="grow col" style={{ gap: 0 }}>
            <span>
              {when(run.started_at)} · {modelOf(run)}
            </span>
            <span className="faint small">
              {t(`tests.status.${run.status}`)} · {t('tests.answered', { n: run.turns, of: run.inputs })} · {t('tests.snapshot', { at: when(run.snapshot?.created_at) })}
            </span>
          </span>
          <button
            className="ghost"
            aria-label={t('common.delete')}
            onClick={async (e) => {
              e.preventDefault();
              if (!confirm(t('tests.delete_run_confirm'))) return;
              qc.setQueryData(['test-runs', workId, set.id], (await del<RunSummary[]>(`/api/works/${workId}/tests/runs/${run.id}`)).filter((r) => r.set.id === set.id));
              setPicked((p) => p.filter((x) => x !== run.id));
            }}
          >
            ×
          </button>
        </label>
      ))}
    </Dialog>
  );
}

function CompareRuns({ workId, ids, onClose }: { workId: string; ids: string[]; onClose: () => void }) {
  const first = useQuery<Run>({ queryKey: ['test-run', workId, ids[0]], queryFn: () => get(`/api/works/${workId}/tests/runs/${ids[0]}`) });
  const second = useQuery<Run>({ queryKey: ['test-run', workId, ids[1]], queryFn: () => get(`/api/works/${workId}/tests/runs/${ids[1]}`) });
  const [a, b] = [first.data, second.data];
  // Oldest on the left.
  const [left, right] = a && b && a.started_at > b.started_at ? [b, a] : [a, b];
  const rows = left && right ? compareRows(left, right) : [];
  return (
    <Dialog title={t('tests.compare_title')} onClose={onClose} closeLabel={t('common.close')} className="wide">
      {left && right && (
        <div className="test-compare">
          <div />
          {[left, right].map((run) => (
            <div key={run.id} className="test-compare-head">
              <strong>{when(run.started_at)}</strong>
              <span className="small">{modelOf(run)}</span>
              <span className="faint small">{t('tests.snapshot', { at: when(run.snapshot?.created_at) })}{run.snapshot?.label ? ` · ${run.snapshot.label}` : ''}</span>
            </div>
          ))}
          {rows.map((row) => (
            <div key={row.index} className="test-compare-row">
              <div className="test-compare-input">{row.inputs.join(' / ')}</div>
              {[row.left, row.right].map((turn, side) => {
                return (
                  <div key={side} className="test-compare-reply">
                    {turn ? turn.reply || (turn.error ? <span className="error-text">{turn.error}</span> : '—') : <span className="faint">{t('tests.not_sent')}</span>}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </Dialog>
  );
}
