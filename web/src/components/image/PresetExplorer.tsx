import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { ApiError, del, get, post, put } from '../../api';
import { t, tm } from '../../i18n';
import { PRESET_ID } from '../../lib/presetFromRecord';
import { PRESET_HANDOFF } from '../../lib/presetHandoff';
import Explorer, { type Facet } from '../explorer/Explorer';
import { useToast } from '../Toasts';
import { useUnsaved } from '../Unsaved';
import PresetEditor, { blankPreset, editable, opened, presetTarget, type Preset } from './PresetEditor';

// Image menu → Style presets (#169): every preset with its one preview, filtered by service, model family, tags, model
// and LoRA; edit one beside the grid, compare up to four, or send one to the generate screen.

const base = (name: string) => name.replace(/^checkpoint::/, '').split(/[\\/]/).pop() ?? name;
const loraNames = (p: Preset) => ((p.settings.loras as { name: string; enabled?: boolean }[] | undefined) ?? []).filter((l) => l.enabled !== false).map((l) => base(l.name));

const facets = (): Facet<Preset>[] => [
  { id: 'target', label: t('presets.facet.target'), values: (p) => [presetTarget(p)] },
  { id: 'tag', label: t('presets.facet.tag'), values: (p) => p.tags },
  { id: 'model', label: t('presets.facet.model'), values: (p) => (p.settings.model ? [base(String(p.settings.model))] : []) },
  { id: 'lora', label: t('presets.facet.lora'), values: loraNames },
];

export default function PresetExplorer({ workId, openGenerate }: { workId: string; openGenerate: () => void }) {
  const [FACETS] = useState(facets);
  const qc = useQueryClient();
  const toast = useToast();
  const fail = (err: unknown) => toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
  // Previews asked for and not back yet: the list is read again until each one's picture changes.
  const [waiting, setWaiting] = useState<Record<string, string>>({});
  const presets = useQuery<Preset[]>({
    queryKey: ['image-presets'],
    queryFn: () => get('/api/image/presets'),
    refetchInterval: Object.keys(waiting).length ? 4000 : false,
  });
  const previewSettings = useQuery<{ preview_seed: number }>({ queryKey: ['image-settings', 'presets'], queryFn: () => get('/api/image/settings/presets') });
  const [seed, setSeed] = useState('');
  useEffect(() => {
    if (previewSettings.data) setSeed(String(previewSettings.data.preview_seed));
  }, [previewSettings.data]);
  useEffect(() => {
    const done = Object.keys(waiting).filter((id) => {
      const p = presets.data?.find((x) => x.id === id);
      return !p || (p.preview?.created_at ?? '') !== waiting[id];
    });
    if (done.length) setWaiting((w) => Object.fromEntries(Object.entries(w).filter(([id]) => !done.includes(id))));
  }, [presets.data, waiting]);

  const [draft, setDraft] = useState<Preset | null>(null);
  const storedPreset = draft ? presets.data?.find((p) => p.id === draft.id) : undefined;
  const dirty = !!draft && (!storedPreset || JSON.stringify(editable(opened(storedPreset))) !== JSON.stringify(editable(draft)));
  useUnsaved('style-presets', dirty);
  const leave = () => !dirty || confirm(t('lib.discard_confirm'));
  const select = (id: string) => {
    if (draft?.id === id || !leave()) return;
    const p = presets.data?.find((x) => x.id === id);
    if (p) setDraft(opened(p));
  };
  const newId = (suggested = '') => {
    const ident = prompt(t('lib.new_id'), suggested)?.trim();
    if (!ident) return null;
    if (!PRESET_ID.test(ident)) return alert(t('presets.bad_id')), null;
    if ((presets.data ?? []).some((p) => p.id === ident)) return alert(t('lib.id_taken', { id: ident })), null;
    return ident;
  };

  async function save(next: Preset) {
    try {
      // The preview record stays as the server has it, even when it was made after this draft was opened.
      const current = presets.data?.find((p) => p.id === next.id);
      const body = { ...editable(next), ...(current?.preview ? { preview: current.preview } : {}) };
      qc.setQueryData(['image-presets'], await put(`/api/image/presets/${next.id}`, body));
      return true;
    } catch (err) {
      fail(err);
      return false;
    }
  }
  async function makePreview(ids: string[]) {
    const before: Record<string, string> = {};
    let queued = 0;
    for (const id of ids) {
      try {
        await post(`/api/image/presets/${id}/preview`);
        before[id] = presets.data?.find((p) => p.id === id)?.preview?.created_at ?? '';
        queued += 1;
      } catch (err) {
        fail(err);
        break;
      }
    }
    if (queued) {
      setWaiting((w) => ({ ...w, ...before }));
      toast({ text: t('presets.preview_queued', { n: queued }) });
    }
  }
  async function saveSeed() {
    const value = Number(seed);
    if (!Number.isInteger(value) || value < 0 || value === previewSettings.data?.preview_seed) return;
    if (!confirm(t('presets.seed_confirm'))) return setSeed(String(previewSettings.data?.preview_seed ?? ''));
    try {
      await put('/api/image/settings/presets', { preview_seed: value });
      await qc.invalidateQueries({ queryKey: ['image-settings', 'presets'] });
      await qc.invalidateQueries({ queryKey: ['image-presets'] });
    } catch (err) {
      fail(err);
    }
  }

  const all = presets.data ?? [];
  const missing = all.filter((p) => p.service === 'comfyui' && (!p.preview_url || p.preview_stale));
  const card = (p: Preset) => (
    <>
      <div className="preset-thumb">
        {p.preview_url ? <img src={p.preview_url} alt="" loading="lazy" /> : <span className="faint small">{waiting[p.id] !== undefined ? t('presets.preview_making') : t('presets.preview_none')}</span>}
        {p.preview_url && p.preview_stale && <span className="chip small warn preset-stale">{t('presets.preview_stale')}</span>}
        {waiting[p.id] !== undefined && p.preview_url && <span className="chip small preset-stale">{t('presets.preview_making')}</span>}
      </div>
      <div className="col" style={{ gap: 2, padding: '6px 8px' }}>
        <strong className="ellipsis">{p.name}</strong>
        <div className="row" style={{ gap: 4, flexWrap: 'wrap' }}>
          <span className="chip small">{presetTarget(p)}</span>
          {p.tags.map((tag) => (
            <span key={tag} className="chip small faint">
              {tag}
            </span>
          ))}
        </div>
      </div>
    </>
  );
  const rows: [string, (p: Preset) => string][] = [
    ['presets.facet.target', presetTarget],
    ['presets.facet.model', (p) => (p.settings.model ? base(String(p.settings.model)) : t('gen.default'))],
    ['presets.facet.lora', (p) => loraNames(p).join(', ')],
    ['gen.sampler', (p) => [p.settings.sampler, p.settings.scheduler].filter(Boolean).join(' · ')],
    ['gen.steps', (p) => [p.settings.steps, p.settings.cfg && `CFG ${p.settings.cfg}`].filter(Boolean).join(' · ')],
    ['gallery.size', (p) => (p.settings.width && p.settings.height ? `${p.settings.width} × ${p.settings.height}` : '')],
    ['gen.artist', (p) => p.artist.positive],
    ['gen.artist_negative', (p) => p.artist.negative],
  ];
  const compare = (items: Preset[]) => (
    <div className="preset-compare" style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}>
      {items.map((p) => (
        <div key={p.id} className="col" style={{ gap: 6 }}>
          <div className="preset-thumb large">{p.preview_url ? <img src={p.preview_url} alt="" /> : <span className="faint">{t('presets.preview_none')}</span>}</div>
          <strong>{p.name}</strong>
          <dl className="kv small">
            {rows.map(([label, value]) => (
              <div key={label}>
                <dt>{t(label)}</dt>
                <dd className={label.startsWith('gen.artist') ? 'mono' : undefined}>{value(p) || '—'}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
    </div>
  );

  const detail = !draft ? (
    <div className="col pad" style={{ gap: 8 }}>
      <p className="faint">{t('presets.about')}</p>
      <p className="faint small">{t('presets.preview_about', { seed: previewSettings.data?.preview_seed ?? '' })}</p>
    </div>
  ) : (
    <div className="col pad" style={{ gap: 8 }}>
      <div className="row">
        <strong className="grow mono">{draft.id}</strong>
        <button className="ghost small" onClick={() => leave() && setDraft(null)}>
          ×
        </button>
      </div>
      {storedPreset?.preview_url && <img className="preset-detail-img" src={storedPreset.preview_url} alt="" />}
      <PresetEditor workId={workId} draft={draft} onChange={setDraft} />
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <button className="primary" disabled={!dirty} onClick={() => save(draft)}>
          {t('common.save')}
        </button>
        <button
          disabled={draft.service !== 'comfyui' || !storedPreset || waiting[draft.id] !== undefined}
          title={draft.service !== 'comfyui' ? t('presets.preview_comfy_only') : dirty ? t('presets.preview_save_first') : undefined}
          onClick={async () => {
            if (dirty && !(await save(draft))) return;
            makePreview([draft.id]);
          }}
        >
          {storedPreset?.preview_url ? t('presets.preview_again') : t('presets.preview_make')}
        </button>
        <button
          disabled={!storedPreset}
          onClick={() => {
            if (!leave()) return;
            sessionStorage.setItem(PRESET_HANDOFF, draft.id);
            window.dispatchEvent(new CustomEvent(PRESET_HANDOFF, { detail: draft.id }));
            openGenerate();
          }}
        >
          {t('presets.apply')}
        </button>
        <button
          disabled={!storedPreset}
          onClick={async () => {
            if (!leave() || !storedPreset) return;
            const ident = newId(`${draft.id}_copy`);
            if (!ident) return;
            const next = { ...editable(storedPreset), id: ident, name: `${storedPreset.name} (${t('presets.copy')})` } as Preset;
            if (await save(next)) setDraft(opened(next));
          }}
        >
          {t('presets.duplicate')}
        </button>
        {storedPreset && (
          <button
            className="danger"
            onClick={async () => {
              if (!confirm(t('lib.delete_confirm', { id: draft.id }))) return;
              try {
                qc.setQueryData(['image-presets'], await del(`/api/image/presets/${draft.id}`));
                setDraft(null);
              } catch (err) {
                fail(err);
              }
            }}
          >
            {t('common.delete')}
          </button>
        )}
      </div>
    </div>
  );

  return (
    <Explorer
      items={all}
      idOf={(p) => p.id}
      search={(p) => [p.id, p.name, p.artist.positive, ...p.tags].join(' ')}
      facets={FACETS}
      card={card}
      detail={detail}
      compare={compare}
      selected={draft?.id ?? null}
      onSelect={select}
      empty={t('presets.empty')}
      toolbar={
        <>
          <label className="row small" style={{ gap: 4 }} title={t('presets.seed_hint')}>
            <span className="muted">{t('presets.seed')}</span>
            <input type="number" style={{ width: 110 }} value={seed} onChange={(e) => setSeed(e.target.value)} onBlur={saveSeed} onKeyDown={(e) => e.key === 'Enter' && saveSeed()} />
          </label>
          <button disabled={!missing.length} onClick={() => confirm(t('presets.preview_all_confirm', { n: missing.length })) && makePreview(missing.map((p) => p.id))}>
            {t('presets.preview_all', { n: missing.length })}
          </button>
          <button
            className="primary"
            onClick={() => {
              if (!leave()) return;
              const ident = newId();
              if (ident) setDraft(blankPreset(ident));
            }}
          >
            {t('presets.new')}
          </button>
        </>
      }
    />
  );
}
