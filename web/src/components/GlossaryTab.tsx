import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { get, put } from '../api';
import { t } from '../i18n';
import { ChipsInput } from './ui';

type Term = { use: string; avoid: string[]; note: string };

export default function GlossaryTab({ workId }: { workId: string }) {
  const qc = useQueryClient();
  const query = useQuery<{ terms: Term[] }>({ queryKey: ['glossary', workId], queryFn: () => get(`/api/works/${workId}/glossary`) });
  const [terms, setTerms] = useState<Term[] | null>(null);
  const dirty = useRef(false);

  useEffect(() => {
    if (query.data && !dirty.current) setTerms(query.data.terms);
  }, [query.data]);

  useEffect(() => {
    if (!terms || !dirty.current) return;
    const timer = setTimeout(async () => {
      // Rows without a term to use are kept on screen but not saved yet.
      await put(`/api/works/${workId}/glossary`, { terms });
      dirty.current = false;
      qc.invalidateQueries({ queryKey: ['check', workId] });
    }, 600);
    return () => clearTimeout(timer);
  }, [terms, workId, qc]);

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
