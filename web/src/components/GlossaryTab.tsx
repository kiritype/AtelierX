import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { ApiError, get, put } from '../api';
import { t, tm } from '../i18n';
import { useToast } from './Toasts';
import { ChipsInput } from './ui';

type Term = { use: string; avoid: string[]; note: string };

export default function GlossaryTab({ workId }: { workId: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const query = useQuery<{ terms: Term[]; revision: string }>({ queryKey: ['glossary', workId], queryFn: () => get(`/api/works/${workId}/glossary`) });
  const [terms, setTerms] = useState<Term[] | null>(null);
  const dirty = useRef(false);
  // The revision the next save starts from: a change made elsewhere since is not overwritten (#90).
  const revision = useRef<string | null>(null);

  useEffect(() => {
    if (query.data && !dirty.current) {
      setTerms(query.data.terms);
      revision.current = query.data.revision;
    }
  }, [query.data]);

  useEffect(() => {
    if (!terms || !dirty.current) return;
    const timer = setTimeout(async () => {
      // Rows without a term to use are kept on screen but not saved yet.
      try {
        const saved = await put<{ revision: string }>(`/api/works/${workId}/glossary`, { terms, base_revision: revision.current });
        revision.current = saved.revision;
        dirty.current = false;
        qc.invalidateQueries({ queryKey: ['check', workId] });
      } catch (err) {
        dirty.current = false;
        const stale = err instanceof ApiError && err.status === 409;
        toast({ text: stale ? t('save.reloaded') : err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
        if (stale) qc.invalidateQueries({ queryKey: ['glossary', workId] });
      }
    }, 600);
    return () => clearTimeout(timer);
  }, [terms, workId, qc, toast]);

  if (!terms) return null;
  const change = (next: Term[]) => {
    dirty.current = true;
    setTerms(next);
  };
  const update = (n: number, term: Term) => change(terms.map((x, i) => (i === n ? term : x)));

  return (
    <div className="pad col" style={{ maxWidth: 900 }}>
      <p className="faint">{t('glossary.note')}</p>
      <table className="plain">
        <thead>
          <tr className="faint">
            <td>{t('glossary.use')}</td>
            <td>{t('glossary.avoid')}</td>
            <td>{t('glossary.memo')}</td>
            <td />
          </tr>
        </thead>
        <tbody>
          {terms.map((term, n) => (
            <tr key={n}>
              <td style={{ width: 160 }}>
                <input value={term.use} onChange={(e) => update(n, { ...term, use: e.target.value })} />
              </td>
              <td>
                <ChipsInput values={term.avoid} onChange={(avoid) => update(n, { ...term, avoid })} placeholder={t('form.keywords_hint')} />
              </td>
              <td>
                <input value={term.note} onChange={(e) => update(n, { ...term, note: e.target.value })} />
              </td>
              <td>
                <button className="ghost" onClick={() => change(terms.filter((_, i) => i !== n))}>
                  ×
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {terms.length === 0 && <div className="faint">{t('glossary.empty')}</div>}
      <div>
        <button onClick={() => change([...terms, { use: '', avoid: [], note: '' }])}>{t('glossary.add')}</button>
      </div>
    </div>
  );
}
