import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { get } from '../../api';
import { t } from '../../i18n';
import type { PixAILora } from '../../lib/pixai';
import type { ServicePanelProps } from './serviceSettings';

type Info = {
  models: { id: string; name: string; type: 'sdxl' | 'dit' }[];
  aspect_ratios: string[];
  sizes: string[];
  modes: string[];
  samplers: string[];
  max_loras: number;
  loras: PixAILora[];
  defaults: Record<string, unknown>;
};
type Picked = { id: string; weight: number; trigger_words?: string };

// The generate screen's settings for PixAI (#43): model (version id), framing, sampling or mode, and up to five of the
// LoRAs registered in Settings. PixAI's API does not tell the cost beforehand.
export default function PixAISettings({ value, onChange }: ServicePanelProps) {
  const info = useQuery<Info>({ queryKey: ['image-service-info', 'pixai'], queryFn: () => get('/api/image/services/pixai/info') });
  const [customModel, setCustomModel] = useState(false);
  if (!info.data) return null;
  const v = { ...info.data.defaults, ...value } as Record<string, any>;
  const set = (change: Record<string, unknown>) => onChange({ ...value, ...change });
  const model = info.data.models.find((m) => m.id === v.model);
  const dit = model?.type === 'dit';
  const picked: Picked[] = v.loras ?? [];
  const registered = info.data.loras;
  const toggleLora = (lora: PixAILora, on: boolean) =>
    set({
      loras: on
        ? [...picked, { id: lora.id, weight: lora.weight, ...(lora.trigger_words ? { trigger_words: lora.trigger_words } : {}) }]
        : picked.filter((p) => p.id !== lora.id),
    });

  return (
    <div className="col" style={{ gap: 8 }}>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('pixai.model')}</span>
        {customModel || !model ? (
          <div className="row">
            <input className="mono grow" value={v.model} placeholder={t('pixai.model_id')} onChange={(e) => set({ model: e.target.value.trim() })} />
            <button className="ghost" onClick={() => (setCustomModel(false), set({ model: info.data!.models[0].id }))}>
              {t('nai.model_list')}
            </button>
          </div>
        ) : (
          <select value={v.model} onChange={(e) => (e.target.value === '*' ? setCustomModel(true) : set({ model: e.target.value }))}>
            {info.data.models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} ({m.type === 'dit' ? 'DiT' : 'SDXL'})
              </option>
            ))}
            <option value="*">{t('pixai.model_custom')}</option>
          </select>
        )}
      </label>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <label className="row" style={{ gap: 4 }}>
          <span className="muted">{t('pixai.aspect_ratio')}</span>
          <select value={v.aspect_ratio} onChange={(e) => set({ aspect_ratio: e.target.value })}>
            {info.data.aspect_ratios.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <label className="row" style={{ gap: 4 }}>
          <span className="muted">{t('pixai.size')}</span>
          <select value={v.size} onChange={(e) => set({ size: e.target.value })}>
            {info.data.sizes.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="row" style={{ gap: 4 }}>
          <span className="muted">{t('nai.seed')}</span>
          <input type="number" style={{ width: 120 }} value={v.seed} onChange={(e) => set({ seed: Number(e.target.value) })} />
        </label>
      </div>
      {dit ? (
        <label className="row" style={{ gap: 4 }}>
          <span className="muted">{t('pixai.mode')}</span>
          <select value={v.mode} onChange={(e) => set({ mode: e.target.value })}>
            {info.data.modes.map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </label>
      ) : (
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <label className="row" style={{ gap: 4 }}>
            <span className="muted">{t('nai.sampler')}</span>
            <select value={v.sampler} onChange={(e) => set({ sampler: e.target.value })}>
              {info.data.samplers.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <label className="row" style={{ gap: 4 }}>
            <span className="muted">{t('nai.steps')}</span>
            <input type="number" style={{ width: 72 }} value={v.steps} onChange={(e) => set({ steps: Number(e.target.value) })} />
          </label>
          <label className="row" style={{ gap: 4 }}>
            <span className="muted">CFG</span>
            <input type="number" step={0.5} style={{ width: 72 }} value={v.cfg_scale} onChange={(e) => set({ cfg_scale: Number(e.target.value) })} />
          </label>
        </div>
      )}
      <label className="row" style={{ gap: 4 }}>
        <input type="checkbox" checked={!!v.prompt_helper} onChange={(e) => set({ prompt_helper: e.target.checked })} />
        {t('pixai.prompt_helper')}
      </label>
      <div className="col" style={{ gap: 4 }}>
        <span className="muted">
          {t('pixai.loras', { n: picked.length, max: info.data.max_loras })}
        </span>
        {registered.length === 0 && <span className="faint small">{t('pixai.no_loras')}</span>}
        {registered.map((lora) => {
          const pick = picked.find((p) => p.id === lora.id);
          return (
            <div key={lora.id} className="row">
              <label className="row grow" style={{ gap: 4 }}>
                <input type="checkbox" checked={!!pick} disabled={!pick && picked.length >= info.data!.max_loras} onChange={(e) => toggleLora(lora, e.target.checked)} />
                {lora.name}
                {lora.trigger_words && <span className="faint small">· {lora.trigger_words}</span>}
              </label>
              {pick && (
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  style={{ width: 72 }}
                  aria-label={t('pixai.lora_weight')}
                  value={pick.weight}
                  onChange={(e) => set({ loras: picked.map((p) => (p.id === lora.id ? { ...p, weight: Number(e.target.value) } : p)) })}
                />
              )}
            </div>
          );
        })}
      </div>
      <p className="faint small">{t('pixai.cost_unknown')}</p>
    </div>
  );
}
