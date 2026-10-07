import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { ApiError, get, patch } from '../api';
import { t, tm } from '../i18n';
import type { WorkInfo } from '../types';
import { useToast } from './Toasts';
import { ChipsInput } from './ui';

function flattenValues(value: any, sources: any, prefix = ''): { key: string; value: any; source: string }[] {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return Object.entries(value).flatMap(([k, v]) => flattenValues(v, sources?.[k], prefix ? `${prefix}.${k}` : k));
  }
  return [{ key: prefix, value, source: typeof sources === 'string' ? sources : 'default' }];
}

export default function WorkSettings({ workId, info }: { workId: string; info: WorkInfo }) {
  const qc = useQueryClient();
  const toast = useToast();
  const doc = info.doc;
  const [tags, setTags] = useState<string[]>(doc.tags ?? []);
  const [scale, setScale] = useState(doc.scale);
  const [language, setLanguage] = useState(doc.language);
  const [char, setChar] = useState(doc.char ?? '');
  const presetIds = new Set(info.presets.map((p) => p.id));
  const providers = useQuery<any>({ queryKey: ['providers'], queryFn: () => get('/api/providers') });

  async function save(changes: Record<string, any>) {
    try {
      await patch(`/api/works/${workId}`, changes);
      qc.invalidateQueries({ queryKey: ['work', workId] });
      qc.invalidateQueries({ queryKey: ['check', workId] });
      toast({ text: t('common.saved') });
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    }
  }

  const rows = flattenValues(info.effective.values, info.effective.sources).filter((r) => !r.key.startsWith('jsx.globals'));

  return (
    <div className="pad col" style={{ maxWidth: 820 }}>
      <h3>{t('window.work_settings')}</h3>
      <div className="row">
        <label className="col grow" style={{ gap: 2 }}>
          <span className="muted">ID</span>
          <input value={doc.id} disabled />
        </label>
        <label className="col grow" style={{ gap: 2 }}>
          <span className="muted">{t('works.scale')}</span>
          <select value={scale} onChange={(e) => setScale(e.target.value)}>
            {['single', 'ensemble', 'simulation'].map((s) => (
              <option key={s} value={s}>
                {t(`scale.${s}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="col grow" style={{ gap: 2 }}>
          <span className="muted">{t('works.language')}</span>
          <select value={language} onChange={(e) => setLanguage(e.target.value)}>
            <option value="ko">한국어</option>
            <option value="en">English</option>
          </select>
        </label>
        {scale === 'single' && (
          <label className="col grow" style={{ gap: 2 }}>
            <span className="muted">{t('work_settings.char')}</span>
            <input value={char} placeholder="C001" onChange={(e) => setChar(e.target.value)} />
          </label>
        )}
      </div>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('works.tags')}</span>
        <ChipsInput values={tags} onChange={setTags} accent={(v) => presetIds.has(v)} placeholder={t('works.tags_hint')} />
        <span className="faint">{t('works.tags_note')}</span>
      </label>
      <div>
        <button className="primary" onClick={() => save({ tags, scale, language, char: char || null })}>
          {t('common.save')}
        </button>
      </div>

      <div className="section-title">{t('work_settings.consent')}</div>
      {(doc.llm_consent ?? []).length === 0 ? (
        <p className="faint">{t('work_settings.consent_none')}</p>
      ) : (
        (doc.llm_consent as string[]).map((id) => (
          <div key={id} className="row">
            <span className="grow">{providers.data?.providers?.[id]?.name ?? id}</span>
            <button onClick={() => save({ llm_consent: (doc.llm_consent as string[]).filter((x) => x !== id) })}>{t('work_settings.consent_revoke')}</button>
          </div>
        ))
      )}

      <div className="section-title">{t('work_settings.platform_rules')}</div>
      <p className="faint">{t('work_settings.platform_note', { linked: info.effective.linked.join(', ') || 'generic' })}</p>
      <table className="plain">
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <td className="mono">{r.key}</td>
              <td>{JSON.stringify(r.value)}</td>
              <td className="faint">{r.source === 'default' ? t('work_settings.src_default') : r.source === 'work' ? t('work_settings.src_work') : r.source}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
