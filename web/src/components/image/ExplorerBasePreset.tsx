import { useQuery } from '@tanstack/react-query';
import { get } from '../../api';
import { t } from '../../i18n';
import type { LoraRef } from '../../imageTypes';
import { loraLabel } from '../../lib/loraLabel';
import { opened, type Preset } from './PresetEditor';
import { settingsKey, type ExplorerDraft } from './styleExplorerDraft';

export default function ExplorerBasePreset({ draft, onChange }: {
  draft: ExplorerDraft; onChange: (draft: ExplorerDraft) => void;
}) {
  const presets = useQuery({ queryKey: ['image-presets'], queryFn: () => get<Preset[]>('/api/image/presets') });
  const key = settingsKey(draft);
  const base = draft.basePresets[key];
  const matching = (presets.data ?? []).filter(p => p.service === draft.service &&
    (p.service !== 'comfyui' || p.family === draft.family));
  const loras = (draft.settings[key]?.loras ?? []) as Partial<LoraRef>[];
  function choose(id: string) {
    const preset = matching.find(p => p.id === id);
    const { loras: _loras, ...generation } = draft.settings[key] ?? {};
    onChange({
      ...draft,
      models: preset ? [] : draft.models,
      settings: { ...draft.settings, [key]: preset ? structuredClone(opened(preset).settings) : generation },
      basePresets: { ...draft.basePresets, [key]: preset
        ? { id: preset.id, name: preset.name, artist: { ...preset.artist } } : undefined },
    });
  }
  return <section className="col explorer-base">
    <label className="col">
      <span>{t('style_explorer.base_preset')}</span>
      <select value={base?.id ?? ''} onChange={event => choose(event.target.value)}>
        <option value="">{t('style_explorer.base_none')}</option>
        {base && !matching.some(p => p.id === base.id) && <option value={base.id}>{base.name}</option>}
        {matching.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
    </label>
    <p className="muted small">{t('style_explorer.base_hint')}</p>
    {base && <details>
      <summary>{t('style_explorer.base_contents', { count: loras.length })}</summary>
      <p className="mono small">{base.artist.positive || '—'}</p>
      {base.artist.negative && <p className="mono small">− {base.artist.negative}</p>}
      <ol className="small">{loras.map((lora, index) => <li key={index}>{loraLabel(lora)}</li>)}</ol>
    </details>}
  </section>;
}
