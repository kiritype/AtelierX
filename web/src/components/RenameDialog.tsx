import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { ApiError, post } from '../api';
import { t, tm } from '../i18n';
import { useToast } from './Toasts';

type Hit = { id: string; path: string | null; where: 'body' | 'keyword' | 'relation' | 'filename'; line?: number; before: string; after: string; josa: boolean };

const TARGETS = ['body', 'keyword', 'relation', 'filename'] as const;

// 04-authoring: 이름 일괄 변경 — preview every place, untick what should stay, then replace in one go.
export default function RenameDialog({
  workId,
  initial = '',
  onClose,
  renamePath,
}: {
  workId: string;
  initial?: string;
  onClose: () => void;
  renamePath: (from: string, to: string) => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [find, setFind] = useState(initial);
  const [replace, setReplace] = useState('');
  const [targets, setTargets] = useState<Set<string>>(new Set(TARGETS));
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());

  async function preview() {
    if (!find.trim()) return;
    const result = await post<Hit[]>(`/api/works/${workId}/rename-text/preview`, { find, replace, targets: [...targets] });
    setHits(result);
    setChosen(new Set(result.map((h) => h.id)));
  }

  async function run() {
    try {
      const result = await post(`/api/works/${workId}/rename-text`, { find, replace, hits: [...chosen] });
      for (const m of result.moved ?? []) {
        const before = hits?.find((h) => h.where === 'filename' && h.after === m.path)?.before;
        if (before) renamePath(before, m.path);
      }
      for (const key of ['tree', 'check', 'relations', 'snapshots', 'search']) qc.invalidateQueries({ queryKey: [key, workId] });
      qc.invalidateQueries({ queryKey: ['item', workId] });
      toast({ text: t('rename.done', { n: chosen.size }) });
      onClose();
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    }
  }

  const groups = new Map<string, Hit[]>();
  for (const hit of hits ?? []) {
    const key = hit.path ?? t('panel.relations');
    groups.set(key, [...(groups.get(key) ?? []), hit]);
  }
  const risky = (hits ?? []).filter((h) => h.josa).length;

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" style={{ width: 720 }}>
        <h3>{t('rename.title')}</h3>
        <div className="row">
          <input autoFocus placeholder={t('rename.find')} value={find} onChange={(e) => (setFind(e.target.value), setHits(null))} />
          →
          <input placeholder={t('rename.replace')} value={replace} onChange={(e) => (setReplace(e.target.value), setHits(null))} onKeyDown={(e) => e.key === 'Enter' && preview()} />
          <button onClick={preview} disabled={!find.trim()}>
            {t('rename.preview')}
          </button>
        </div>
        <div className="row" style={{ flexWrap: 'wrap' }}>
          {TARGETS.map((target) => (
            <label key={target} className="row" style={{ gap: 4 }}>
              <input
                type="checkbox"
                checked={targets.has(target)}
                onChange={(e) => {
                  const next = new Set(targets);
                  if (e.target.checked) next.add(target);
                  else next.delete(target);
                  setTargets(next);
                  setHits(null);
                }}
              />
              {t(`rename.where.${target}`)}
            </label>
          ))}
        </div>
        <p className="faint">{t('rename.note')}</p>
        {hits && hits.length === 0 && <div className="empty">{t('rename.none')}</div>}
        {risky > 0 && <div className="warn-text">{t('rename.josa_warning', { n: risky })}</div>}
        {hits && hits.length > 0 && (
          <div className="rename-list">
            {[...groups.entries()].map(([path, list]) => (
              <div key={path}>
                <div className="section-title">{path}</div>
                {list.map((hit) => (
                  <label key={hit.id} className={`rename-hit${hit.josa ? ' josa' : ''}`}>
                    <input
                      type="checkbox"
                      checked={chosen.has(hit.id)}
                      onChange={(e) => {
                        const next = new Set(chosen);
                        if (e.target.checked) next.add(hit.id);
                        else next.delete(hit.id);
                        setChosen(next);
                      }}
                    />
                    <span className="faint">{hit.where === 'body' ? t('rename.line', { n: hit.line ?? 0 }) : t(`rename.where.${hit.where}`)}</span>
                    <span className="grow">
                      <span className="del">{hit.before}</span>
                      <br />
                      <span className="ins">{hit.after}</span>
                    </span>
                    {hit.josa && <span className="chip">{t('rename.josa')}</span>}
                  </label>
                ))}
              </div>
            ))}
          </div>
        )}
        <div className="actions">
          <button onClick={onClose}>{t('common.cancel')}</button>
          <button className="primary" disabled={!hits || chosen.size === 0 || !replace} onClick={run}>
            {t('rename.run', { n: chosen.size })}
          </button>
        </div>
      </div>
    </div>
  );
}
