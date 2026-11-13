import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { ApiError, get } from '../../api';
import { t, tm } from '../../i18n';
import type { PromptSource } from '../../imageTypes';
import { fits } from '../../lib/fragments';
import { cleanPrompt, replaceSource } from '../../lib/singlePromptSources';
import './SinglePromptMaterials.css';

type Material = { id: string; name: string; targets?: string[]; prompt?: string[]; negative?: string[] };
type Design = { id: string; name: string; has_design: boolean };
export type StyleChoice = { id: string; name: string; preview_url?: string; preview_stale?: boolean };
export const tagsText = (tags: string[] = []) => [...new Set(tags.map(cleanPrompt).filter(Boolean))].join(', ');

export function StyleThumbnails({ presets, selected, choose, disabled }: { presets: StyleChoice[]; selected: string; choose: (id: string) => void; disabled?: boolean }) {
  const [search, setSearch] = useState('');
  const shown = presets.filter(preset => preset.name.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  return <details className="prompt-materials style-picker">
    <summary>{t('materials.browse_styles')}</summary>
    <input type="search" aria-label={t('materials.search_styles')} value={search} onChange={event => setSearch(event.target.value)} />
    <div className="style-thumbnail-list">{shown.map(preset => <button key={preset.id} type="button" className={selected === preset.id ? 'is-selected' : ''} aria-pressed={selected === preset.id}
      disabled={disabled} onClick={() => choose(preset.id)} title={preset.name}>
      {preset.preview_url ? <img src={preset.preview_url} alt="" loading="lazy" /> : <span className="style-thumbnail-placeholder" aria-hidden="true">◇</span>}
      <span>{preset.name}</span>{preset.preview_stale && <small>{t('materials.stale_preview')}</small>}
    </button>)}</div>
    {!shown.length && <p className="faint">{t('materials.no_styles')}</p>}
  </details>;
}

export default function SinglePromptMaterials({ workId, target, sources, change, positive, negative, openLibrary }: {
  workId?: string; target: string; sources: PromptSource[]; change: (update: (sources: PromptSource[]) => PromptSource[]) => void;
  positive: string; negative: string; openLibrary?: () => void;
}) {
  const designs = useQuery<Design[]>({ queryKey: ['image-designs', workId], queryFn: () => get(`/api/works/${workId}/image/designs`), enabled: !!workId });
  const expressions = useQuery<Record<string, Material>>({ queryKey: ['image-lib', 'expressions', workId], queryFn: () => get(`/api/image/library/expressions${workId ? `?work=${workId}` : ''}`) });
  const [character, setCharacter] = useState('');
  const [expression, setExpression] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const addCharacter = async () => {
    const selected = (Array.isArray(designs.data) ? designs.data : []).find(item => item.id === character);
    if (!selected || pending) return;
    setPending(true); setError('');
    try {
      const result = await get<{ design: { appearance?: { prompt?: string[]; negative?: string[] } } }>(`/api/works/${workId}/image/characters/${encodeURIComponent(selected.id)}`);
      change(current => replaceSource(current, 'character', { kind: 'character', id: selected.id, name: selected.name,
        positive: tagsText(result.design.appearance?.prompt), negative: tagsText(result.design.appearance?.negative) }));
    } catch (err) { setError(err instanceof ApiError ? tm(err.msg) : String(err)); }
    finally { setPending(false); }
  };
  const addExpression = () => {
    const selected = expressions.data?.[expression];
    if (!selected) return;
    change(current => replaceSource(current, 'expression', { kind: 'expression', id: selected.id, name: selected.name,
      positive: tagsText(selected.prompt), negative: tagsText(selected.negative) }));
  };
  return <section className="prompt-materials" aria-label={t('materials.title')}>
    <h4>{t('materials.title')}</h4>
    <p className="faint small">{t(workId ? 'materials.replace_note' : 'materials.global_replace_note')}</p>
    {workId && <div className="prompt-material-picker"><label>{t('materials.character')}<select value={character} onChange={event => setCharacter(event.target.value)} disabled={pending}>
      <option value="">{t('materials.choose')}</option>{(Array.isArray(designs.data) ? designs.data : []).filter(item => item.has_design).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
    </select></label><button type="button" disabled={!character || pending} onClick={addCharacter}>{t('materials.apply_character')}</button></div>}
    <div className="prompt-material-picker"><label>{t('materials.expression')}<select value={expression} onChange={event => setExpression(event.target.value)}>
      <option value="">{t('materials.choose')}</option>{Object.values(expressions.data ?? {}).filter(item => fits(item, target)).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
    </select></label><button type="button" disabled={!expression || pending} onClick={addExpression}>{t('materials.apply_expression')}</button></div>
    {error && <p role="alert">{error}</p>}
    {openLibrary && <button type="button" className="ghost" onClick={openLibrary}>{t('materials.open_library')}</button>}
    <details className="prompt-source-detail"><summary>{t('materials.sources')}</summary>
      <p className="faint small">{t('materials.snapshot_note')}</p>
      {[{ kind: 'direct', id: '', name: '', positive: cleanPrompt(positive), negative: cleanPrompt(negative) } as PromptSource, ...sources].map(source => <article key={source.kind}>
        <div className="row"><strong className="grow">{t(`materials.${source.kind}`)}{source.name ? ` · ${source.name}` : ''}</strong>
          {source.kind !== 'direct' && <button type="button" onClick={() => change(current => replaceSource(current, source.kind))} disabled={pending} aria-label={t('materials.remove', { name: source.name || t(`materials.${source.kind}`) })}>×</button>}</div>
        <pre>{source.positive || '—'}</pre>{source.negative && <pre>− {source.negative}</pre>}
      </article>)}
    </details>
  </section>;
}
