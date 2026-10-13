import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, get, put } from '../api';
import { t, tm } from '../i18n';
import { createSaver } from '../lib/exampleSaver';
import { useUnsaved } from './Unsaved';
import { ChipsInput } from './ui';

type Term = { use: string; avoid: string[]; note: string };

export default function GlossaryTab({ workId }: { workId: string }) {
  const qc = useQueryClient();
  const query = useQuery<{ terms: Term[]; revision: string }>({ queryKey: ['glossary', workId], queryFn: () => get(`/api/works/${workId}/glossary`) });
  const [terms, setTerms] = useState<Term[] | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saveError, setSaveError] = useState('');
  // The revision the next save starts from: a change made elsewhere since is not overwritten (#90).
  const revision = useRef<string | null>(null);
  const failure = (err: unknown) => setSaveError(err instanceof ApiError && err.status === 409 ? t('save.conflict_preserved') : err instanceof ApiError ? tm(err.msg) : String(err));
  const saver = useMemo(() => createSaver<string>(async (_, text) => {
    const terms: Term[] = JSON.parse(text);
    const saved = await put<{ revision: string }>(`/api/works/${workId}/glossary`, { terms, base_revision: revision.current });
    revision.current = saved.revision;
    await qc.cancelQueries({ queryKey: ['glossary', workId] });
    return { terms, revision: saved.revision };
  }, {
    delay: 600,
    onChange: setDirty,
    onSaved: (_, saved, clean) => {
      setSaveError('');
      if (clean) qc.setQueryData(['glossary', workId], saved);
      qc.invalidateQueries({ queryKey: ['check', workId] });
    },
    onError: failure,
  }), [workId, qc]);
  const save = async () => {
    try {
      return (await saver.flush()).clean;
    } catch (err) {
      failure(err);
      return false;
    }
  };
  useUnsaved('glossary', dirty, save);
  useEffect(() => {
    saver.activate();
    return () => saver.dispose();
  }, [saver]);

  useEffect(() => {
    if (query.data && !saver.dirty) {
      setTerms(query.data.terms);
      revision.current = query.data.revision;
    }
  }, [query.data, saver]);

  if (!terms) return null;
  const change = (next: Term[]) => {
    setTerms(next);
    saver.edit(workId, JSON.stringify(next));
  };
  const update = (n: number, term: Term) => change(terms.map((x, i) => (i === n ? term : x)));

  return (
    <div className="pad col" style={{ maxWidth: 900 }}>
      {saveError && <div role="alert">{saveError} <button onClick={save}>{t('common.save')}</button></div>}
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
