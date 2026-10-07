import { useQuery } from '@tanstack/react-query';
import { get } from '../../api';
import { t } from '../../i18n';
import { ChipsInput } from '../ui';
import GenSettings, { type GenerationSettings } from './GenSettings';
import NovelAISettings from './NovelAISettings';
import PixAISettings from './PixAISettings';
import { SERVICE_NAMES } from './serviceSettings';

// A style preset (#169, decision 0026): one service (and on ComfyUI one model family), its settings and the artist tags.
export type Preset = {
  id: string;
  name: string;
  service: string;
  family: string;
  tags: string[];
  settings: GenerationSettings & Record<string, unknown>;
  common: string[];
  artist: { positive: string; negative: string };
  preview?: { seed: number; hash: string; created_at: string };
  preview_url?: string;
  preview_stale?: boolean;
};
export const PRESET_SERVICES = ['comfyui', 'novelai', 'pixai'];

export const presetTarget = (p: Pick<Preset, 'service' | 'family'>) =>
  p.service === 'comfyui' ? (p.family === 'sdxl' ? 'SDXL·IL' : 'Anima') : (SERVICE_NAMES[p.service] ?? p.service);

// ComfyUI presets carry their family in the settings too, as the generation settings form expects.
export const opened = (p: Preset): Preset => (p.service === 'comfyui' ? { ...p, settings: { ...p.settings, family: p.family as 'anima' | 'sdxl' } } : p);

// What the editor changes: the preview belongs to the server (it is recorded when a preview is made).
export const editable = (p: Preset) => {
  const { preview: _preview, preview_url: _url, preview_stale: _stale, ...rest } = p;
  return rest;
};

export const blankPreset = (id: string): Preset => ({
  id,
  name: id,
  service: 'comfyui',
  family: 'anima',
  tags: [],
  settings: { family: 'anima' },
  common: [],
  artist: { positive: '', negative: '' },
});

type Common = { id: string; name: string };

export default function PresetEditor({ workId, draft, onChange }: { workId: string; draft: Preset; onChange: (draft: Preset) => void }) {
  const commons = useQuery<Record<string, Common>>({ queryKey: ['image-lib', 'common', workId], queryFn: () => get(`/api/image/library/common?work=${workId}`) });
  const set = (patch: Partial<Preset>) => onChange({ ...draft, ...patch });
  const toggle = (list: string[], id: string, on: boolean) => (on ? [...list, id] : list.filter((x) => x !== id));
  return (
    <div className="col" style={{ gap: 8 }}>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('lib.name')}</span>
        <input value={draft.name} onChange={(e) => set({ name: e.target.value })} />
      </label>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('gen.service')}</span>
        <div className="seg">
          {PRESET_SERVICES.map((s) => (
            <button
              key={s}
              className={draft.service === s ? 'on' : ''}
              onClick={() => set({ service: s, family: s === 'comfyui' ? 'anima' : s, settings: s === 'comfyui' ? { family: 'anima' } : {} })}
            >
              {SERVICE_NAMES[s] ?? s}
            </button>
          ))}
        </div>
      </label>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('lib.preset_tags')}</span>
        <ChipsInput values={draft.tags} onChange={(tags) => set({ tags })} placeholder={t('lib.preset_tags_hint')} />
      </label>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('gen.artist')}</span>
        <textarea rows={3} value={draft.artist.positive} placeholder={t('presets.artist_hint')} onChange={(e) => set({ artist: { ...draft.artist, positive: e.target.value } })} />
      </label>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('gen.artist_negative')}</span>
        <textarea rows={2} value={draft.artist.negative} onChange={(e) => set({ artist: { ...draft.artist, negative: e.target.value } })} />
      </label>
      {draft.service === 'comfyui' ? (
        <GenSettings value={draft.settings} onChange={(settings) => set({ settings, family: settings.family ?? 'anima' })} />
      ) : draft.service === 'novelai' ? (
        <NovelAISettings value={draft.settings} onChange={(settings) => set({ settings })} />
      ) : (
        <PixAISettings value={draft.settings} onChange={(settings) => set({ settings })} />
      )}
      <div className="col" style={{ gap: 2 }}>
        <span className="muted">{t('lib.kind.common')}</span>
        <div className="row" style={{ flexWrap: 'wrap' }}>
          {Object.values(commons.data ?? {}).map((c) => (
            <label key={c.id} className="row" style={{ gap: 4 }}>
              <input type="checkbox" checked={draft.common.includes(c.id)} onChange={(e) => set({ common: toggle(draft.common, c.id, e.target.checked) })} />
              {c.name}
            </label>
          ))}
        </div>
        <span className="faint">{t('lib.preset_common_note')}</span>
      </div>
    </div>
  );
}
