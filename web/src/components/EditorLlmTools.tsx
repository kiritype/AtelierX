import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { ApiError, get, post } from '../api';
import { t, tm } from '../i18n';
import type { TreeEntry } from '../types';
import { useToast } from './Toasts';
import { Dialog } from './ui';
import RunLlmSelector, { type LlmOverride } from './RunLlmSelector';

type Action = 'compression' | 'content_review' | 'consistency' | 'format';
const flatten = (rows: TreeEntry[]): TreeEntry[] => rows.flatMap((row) => row.type === 'folder' ? flatten(row.children ?? []) : [row]);

export default function EditorLlmTools({ workId, path, beforeRun }: { workId: string; path: string; beforeRun: () => Promise<boolean> }) {
  const [action, setAction] = useState<Action | ''>('');
  const [instructions, setInstructions] = useState('');
  const [target, setTarget] = useState('');
  const [compare, setCompare] = useState<string[]>([]);
  const [llm, setLlm] = useState<LlmOverride>();
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const tree = useQuery<TreeEntry[]>({ queryKey: ['tree', workId], queryFn: () => get(`/api/works/${workId}/tree`) });
  const run = async () => {
    setBusy(true);
    try {
      if (!(await beforeRun())) {
        toast({ text: t('llm_tools.save_first'), tone: 'error' });
        return;
      }
      const body = action === 'compression'
        ? { path, target_size: target === '' ? undefined : Number(target), instructions, llm }
        : { path, instruction: instructions, mode: action === 'format' && instructions.trim() ? 'template' : 'tidy', template: action === 'format' ? instructions : undefined, compare_paths: [path, ...compare], llm };
      await post(`/api/works/${workId}/${action === 'compression' ? 'compress' : `editor/${action.replace('_', '-')}`}`, body);
      toast({ text: t('llm_tools.queued') });
      setAction('');
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    } finally { setBusy(false); }
  };
  return <>
    <select aria-label={t('llm_tools.title')} className="llm-tools-menu" value="" onChange={(e) => { setAction(e.target.value as Action); setInstructions(''); setCompare([]); setLlm(undefined); }}>
      <option value="">{t('llm_tools.title')} ▾</option>
      {(['compression', 'content_review', 'consistency', 'format'] as Action[]).map((item) => <option key={item} value={item}>{t(`llm_tools.${item}`)}</option>)}
    </select>
    {action && <Dialog title={t(`llm_tools.${action}`)} onClose={() => !busy && setAction('')} actions={<button className="primary" disabled={busy || (action === 'consistency' && !compare.length) || (action === 'compression' && target !== '' && (!Number.isInteger(Number(target)) || Number(target) <= 0))} onClick={run}>{t('llm_tools.run')}</button>}>
      <div className="col">
        <p>{t('llm_tools.scope', { path })}</p>
        <RunLlmSelector task={action === 'compression' || action === 'format' ? 'compression' : 'consistency'} value={llm} onChange={setLlm} disabled={busy} />
        {action === 'compression' && <label className="col">{t('llm_tools.target')}<input type="number" min={1} step={1} value={target} onChange={(e) => setTarget(e.target.value)} /></label>}
        {action === 'consistency' && <fieldset className="col" style={{ maxHeight: 220, overflow: 'auto' }}><legend>{t('llm_tools.compare')}</legend>
          {flatten(tree.data ?? []).filter((item) => item.type === 'item' && item.path !== path && item.kind !== 'jsx').map((item) => <label key={item.path}><input type="checkbox" checked={compare.includes(item.path)} onChange={(e) => setCompare(e.target.checked ? [...compare, item.path] : compare.filter((p) => p !== item.path))} /> {item.path}</label>)}
        </fieldset>}
        <label className="col">{t(action === 'format' ? 'llm_tools.format_hint' : 'llm_tools.instructions')}<textarea rows={4} value={instructions} onChange={(e) => setInstructions(e.target.value)} /></label>
        <p className="faint">{t('llm_tools.review_note')}</p>
      </div>
    </Dialog>}
  </>;
}
