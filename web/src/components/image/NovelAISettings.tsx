import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { ApiError, get } from '../../api';
import { t, tm } from '../../i18n';
import type { ServicePanelProps } from './serviceSettings';

type Info = {
  models: { id: string; name: string }[];
  samplers: string[];
  noise_schedules: string[];
  defaults: Record<string, unknown>;
  free: { pixels: number; steps: number };
};
type Account = { tier: number | null; active: boolean | null; anlas: number | null; opus: boolean };

const SIZES = [
  { label: 'size_portrait', width: 832, height: 1216 },
  { label: 'size_landscape', width: 1216, height: 832 },
  { label: 'size_square', width: 1024, height: 1024 },
];

// Whether one image with these settings stays inside what an Opus subscription makes without Anlas.
export function freeForOpus(width: number, height: number, steps: number, free: { pixels: number; steps: number }) {
  return width * height <= free.pixels && steps <= free.steps;
}

// The generate screen's settings for NovelAI (#42): model (V4.5, V5 …), size, sampling, and the account's Anlas.
export default function NovelAISettings({ value, onChange }: ServicePanelProps) {
  const info = useQuery<Info>({ queryKey: ['image-service-info', 'novelai'], queryFn: () => get('/api/image/services/novelai/info'), staleTime: Infinity });
  const account = useQuery<Account, ApiError>({
    queryKey: ['image-service-account', 'novelai'],
    queryFn: () => get('/api/image/services/novelai/account'),
    retry: false,
    staleTime: 60_000,
  });
  const [customModel, setCustomModel] = useState(false);
  if (!info.data) return null;
  const v = { ...info.data.defaults, ...value } as Record<string, any>;
  const set = (change: Record<string, unknown>) => onChange({ ...value, ...change });
  const known = info.data.models.some((m) => m.id === v.model);
  const num = (key: string, step = 1) => (
    <input type="number" step={step} style={{ width: 80 }} value={v[key]} onChange={(e) => set({ [key]: Number(e.target.value) })} />
  );
  const free = freeForOpus(v.width, v.height, v.steps, info.data.free);

  return (
    <div className="col" style={{ gap: 8 }}>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('nai.model')}</span>
        {customModel || !known ? (
          <div className="row">
            <input className="mono grow" value={v.model} placeholder="nai-diffusion-…" onChange={(e) => set({ model: e.target.value.trim() })} />
            <button className="ghost" onClick={() => (setCustomModel(false), set({ model: info.data!.models[0].id }))}>
              {t('nai.model_list')}
            </button>
          </div>
        ) : (
          <select value={v.model} onChange={(e) => (e.target.value === '*' ? setCustomModel(true) : set({ model: e.target.value }))}>
            {info.data.models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} ({m.id})
              </option>
            ))}
            <option value="*">{t('nai.model_custom')}</option>
          </select>
        )}
      </label>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <span className="muted">{t('nai.size')}</span>
        {SIZES.map((size) => (
          <button key={size.label} className={v.width === size.width && v.height === size.height ? 'primary' : ''} onClick={() => set({ width: size.width, height: size.height })}>
            {t(`nai.${size.label}`)}
          </button>
        ))}
        {num('width', 64)}×{num('height', 64)}
      </div>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <label className="row" style={{ gap: 4 }}>
          <span className="muted">{t('nai.steps')}</span>
          {num('steps')}
        </label>
        <label className="row" style={{ gap: 4 }}>
          <span className="muted">{t('nai.scale')}</span>
          {num('scale', 0.1)}
        </label>
        <label className="row" style={{ gap: 4 }}>
          <span className="muted">{t('nai.seed')}</span>
          <input type="number" style={{ width: 120 }} value={v.seed} onChange={(e) => set({ seed: Number(e.target.value) })} />
        </label>
      </div>
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
          <span className="muted">{t('nai.noise_schedule')}</span>
          <select value={v.noise_schedule} onChange={(e) => set({ noise_schedule: e.target.value })}>
            {info.data.noise_schedules.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <label className="row" style={{ gap: 4 }}>
          <input type="checkbox" checked={v.quality_toggle !== false} onChange={(e) => set({ quality_toggle: e.target.checked })} />
          {t('nai.quality_toggle')}
        </label>
        <label className="row" style={{ gap: 4 }}>
          <span className="muted">{t('nai.uc_preset')}</span>
          <select value={v.uc_preset} onChange={(e) => set({ uc_preset: Number(e.target.value) })}>
            {[0, 1, 2, 3, 4].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="row small">
        {account.data ? (
          <span className="faint">
            {account.data.anlas != null ? t('nai.anlas', { n: account.data.anlas.toLocaleString() }) : t('nai.anlas_unknown')}
            {account.data.opus && ` · ${free ? t('nai.free_opus') : t('nai.not_free')}`}
          </span>
        ) : account.error ? (
          <span className="warn-text">{tm(account.error.msg)}</span>
        ) : (
          <span className="faint">{t('nai.account_loading')}</span>
        )}
        <button className="ghost small" onClick={() => account.refetch()}>
          {t('nai.account_refresh')}
        </button>
      </div>
    </div>
  );
}
