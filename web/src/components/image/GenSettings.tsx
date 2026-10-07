import { useQuery } from '@tanstack/react-query';
import { get } from '../../api';
import { t, tm } from '../../i18n';

export type Lora = { name: string; strength_model: number; strength_clip: number; enabled?: boolean };
// After the first pass (#168): enlarge and redraw lightly, then redraw chosen parts.
export type Upscale = { model?: string; scale: number; steps: number; denoise: number; cfg?: number };
export type Detailer = { stages: Partial<Record<Stage, number>>; steps: number };
type Stage = 'face' | 'eye' | 'mouth' | 'hand';
const STAGES: Stage[] = ['face', 'eye', 'mouth', 'hand'];
const UPSCALE_DEFAULT = { scale: 1.5, steps: 12, denoise: 0.3 };
// The eyes are off by default: in trials the eye pass smeared highlights.
const DETAILER_DEFAULT: Detailer = { stages: { face: 0.35, hand: 0.4 }, steps: 20 };
const STAGE_DEFAULT: Record<Stage, number> = { face: 0.35, eye: 0.3, mouth: 0.3, hand: 0.4 };
export type GenerationSettings = {
  family?: 'anima' | 'sdxl';
  model?: string;
  text_encoder?: string;
  vae?: string;
  sampler?: string;
  scheduler?: string;
  steps?: number;
  cfg?: number;
  width?: number;
  height?: number;
  seed?: number;
  clip_skip?: number;
  loras?: Lora[];
  shift?: number | null;
  upscale?: Upscale | null;
  detailer?: Detailer | null;
};

export type Catalog = {
  connected: boolean;
  error?: any;
  models: string[];
  text_encoders: string[];
  vaes: string[];
  loras: string[];
  samplers: string[];
  schedulers: string[];
  defaults: GenerationSettings;
  upscale_models?: string[];
  nodes?: { upscale?: boolean; detailer?: boolean };
  families?: { models?: Record<string, string | null>; loras?: Record<string, string | null> };
};

// Family defaults (anima: 32 steps, CFG 5, er_sde/simple, 1536²; SDXL·IL: 28 steps, CFG 5, euler_ancestral/normal, 1024², clip skip 2).
export const FAMILY_DEFAULTS: Record<'anima' | 'sdxl', GenerationSettings> = {
  anima: { steps: 32, cfg: 5, sampler: 'er_sde', scheduler: 'simple', width: 1536, height: 1536 },
  sdxl: { steps: 28, cfg: 5, sampler: 'euler_ancestral', scheduler: 'normal', width: 1024, height: 1024, clip_skip: 2 },
};

export function useCatalog() {
  return useQuery<Catalog>({ queryKey: ['image-catalog'], queryFn: () => get('/api/image/catalog'), staleTime: 60_000 });
}

const base = (name: string) => name.replace(/^checkpoint::/, '').split(/[\\/]/).pop();

export default function GenSettings({ value, onChange }: { value: GenerationSettings; onChange: (value: GenerationSettings) => void }) {
  const catalog = useCatalog();
  const c = catalog.data;
  if (!c) return null;
  if (!c.connected) return <div className="warn-text">{t('gen.not_connected')} {c.error ? tm(c.error) : ''}</div>;
  const family = value.family ?? 'anima';
  const fam = (kind: 'models' | 'loras', name: string) => c.families?.[kind]?.[name] ?? null;
  const models = c.models.filter((m) => {
    const f = fam('models', m);
    if (family === 'sdxl') return m.startsWith('checkpoint::') && (f === 'sdxl' || f === null);
    return f === 'anima' || f === null;
  });
  // SDXL needs a checkpoint, so switching families picks the first model of that family.
  const firstModel = (f: 'anima' | 'sdxl') =>
    c.models.find((m) => (f === 'sdxl' ? m.startsWith('checkpoint::') && fam('models', m) === 'sdxl' : fam('models', m) === 'anima'));
  const loras = c.loras.filter((l) => (fam('loras', l) === family || fam('loras', l) === null));
  const set = (patch: GenerationSettings) => onChange({ ...value, ...patch });
  const num = (key: keyof GenerationSettings, label: string, step = 1, width = 72) => (
    <label className="col gen-field">
      <span className="muted">{label}</span>
      <input type="number" step={step} style={{ width }} value={(value[key] as number | undefined) ?? ''} onChange={(e) => set({ [key]: e.target.value === '' ? undefined : Number(e.target.value) })} />
    </label>
  );
  const pick = (key: keyof GenerationSettings, label: string, options: string[], allowEmpty?: string) => (
    <label className="col gen-field">
      <span className="muted">{label}</span>
      <select value={(value[key] as string | undefined) ?? ''} onChange={(e) => set({ [key]: e.target.value || undefined })}>
        {allowEmpty !== undefined && <option value="">{allowEmpty}</option>}
        {options.map((o) => (
          <option key={o} value={o}>
            {base(o)}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="col gen-settings">
      <div className="row" style={{ flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <label className="col gen-field">
          <span className="muted">{t('gen.family')}</span>
          <div className="seg">
            {(['anima', 'sdxl'] as const).map((f) => (
              <button
                key={f}
                className={family === f ? 'on' : ''}
                onClick={() => onChange({ family: f, ...FAMILY_DEFAULTS[f], model: firstModel(f), seed: value.seed, loras: [] })}
              >
                {f === 'anima' ? 'Anima' : 'SDXL·IL'}
              </button>
            ))}
          </div>
        </label>
        {pick('model', t('gen.model'), models, t('gen.default'))}
        {family === 'anima' && pick('text_encoder', t('gen.text_encoder'), c.text_encoders, t('gen.default'))}
        {pick('vae', family === 'sdxl' ? t('gen.vae_override') : t('gen.vae'), c.vaes, family === 'sdxl' ? t('gen.builtin') : t('gen.default'))}
      </div>
      <div className="row" style={{ flexWrap: 'wrap', alignItems: 'flex-end' }}>
        {pick('sampler', t('gen.sampler'), c.samplers, t('gen.default'))}
        {pick('scheduler', t('gen.scheduler'), c.schedulers, t('gen.default'))}
        {num('steps', t('gen.steps'))}
        {num('cfg', 'CFG', 0.5)}
        {num('width', t('gen.width'), 16, 84)}
        {num('height', t('gen.height'), 16, 84)}
        {family === 'sdxl' && num('clip_skip', 'clip skip')}
        <label className="col gen-field">
          <span className="muted">{t('gen.seed')}</span>
          <input type="number" style={{ width: 140 }} value={value.seed ?? -1} onChange={(e) => set({ seed: Number(e.target.value) })} title={t('gen.seed_hint')} />
        </label>
      </div>
      <div className="col" style={{ gap: 4 }}>
        <span className="muted">{t('gen.loras')}</span>
        {(value.loras ?? []).map((lora, n) => (
          <div key={n} className={lora.enabled === false ? 'row faint' : 'row'}>
            <input
              type="checkbox"
              checked={lora.enabled !== false}
              title={t('gen.lora_enabled')}
              aria-label={t('gen.lora_enabled')}
              onChange={(e) => set({ loras: (value.loras ?? []).map((x, i) => (i === n ? { ...x, enabled: e.target.checked ? undefined : false } : x)) })}
            />
            <select
              value={lora.name}
              onChange={(e) => set({ loras: (value.loras ?? []).map((x, i) => (i === n ? { ...x, name: e.target.value } : x)) })}
            >
              {[lora.name, ...loras.filter((l) => l !== lora.name)].map((l) => (
                <option key={l} value={l}>
                  {base(l)}
                </option>
              ))}
            </select>
            <input
              type="number"
              step={0.05}
              style={{ width: 72 }}
              value={lora.strength_model}
              title={t('gen.lora_strength')}
              onChange={(e) =>
                set({ loras: (value.loras ?? []).map((x, i) => (i === n ? { ...x, strength_model: Number(e.target.value), strength_clip: Number(e.target.value) } : x)) })
              }
            />
            <button className="ghost" onClick={() => set({ loras: (value.loras ?? []).filter((_, i) => i !== n) })}>
              ×
            </button>
          </div>
        ))}
        {loras.length > 0 && (
          <div>
            <button onClick={() => set({ loras: [...(value.loras ?? []), { name: loras[0], strength_model: 1, strength_clip: 1 }] })}>{t('gen.add_lora')}</button>
          </div>
        )}
      </div>
      {family === 'anima' && (
        <label className="col gen-field">
          <span className="muted">{t('gen.shift')}</span>
          <div className="row">
            <input type="number" step={0.5} min={0.5} max={20} style={{ width: 72 }} value={value.shift ?? ''} onChange={(e) => set({ shift: e.target.value === '' ? null : Number(e.target.value) })} />
            <span className="faint small">{t('gen.shift_hint')}</span>
          </div>
        </label>
      )}
      <UpscaleFields value={value} set={set} catalog={c} />
      <DetailerFields value={value} set={set} catalog={c} />
    </div>
  );
}

function UpscaleFields({ value, set, catalog }: { value: GenerationSettings; set: (patch: GenerationSettings) => void; catalog: Catalog }) {
  const up = value.upscale;
  const models = catalog.upscale_models ?? [];
  const missing = catalog.nodes?.upscale === false;
  const change = (patch: Partial<Upscale>) => set({ upscale: { ...(up as Upscale), ...patch } });
  const w = value.width ?? 0;
  const h = value.height ?? 0;
  return (
    <div className="col gen-stage">
      <label className="row" style={{ gap: 6 }}>
        <input type="checkbox" checked={!!up} disabled={missing && !up} onChange={(e) => set({ upscale: e.target.checked ? { model: models[0], ...UPSCALE_DEFAULT } : null })} />
        <strong>{t('gen.upscale')}</strong>
      </label>
      {missing && <span className="warn-text small">{t('gen.upscale_missing')}</span>}
      {up && (
        <>
          <div className="row" style={{ flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <label className="col gen-field">
              <span className="muted">{t('gen.upscale_model')}</span>
              <select value={up.model ?? ''} onChange={(e) => change({ model: e.target.value })}>
                {models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </label>
            <Num label={t('gen.upscale_scale')} value={up.scale} step={0.25} onChange={(v) => change({ scale: v ?? 1.5 })} />
            <Num label={t('gen.steps')} value={up.steps} onChange={(v) => change({ steps: v ?? 12 })} />
            <Num label="denoise" value={up.denoise} step={0.05} onChange={(v) => change({ denoise: v ?? 0.3 })} />
            <Num label="CFG" value={up.cfg} step={0.5} placeholder={String(value.cfg ?? '')} onChange={(v) => change({ cfg: v })} />
          </div>
          <span className="faint small">
            {t('gen.upscale_size', { from: `${w}×${h}`, to: `${Math.round(w * up.scale)}×${Math.round(h * up.scale)}` })} · {t('gen.upscale_hint')}
          </span>
        </>
      )}
    </div>
  );
}

function DetailerFields({ value, set, catalog }: { value: GenerationSettings; set: (patch: GenerationSettings) => void; catalog: Catalog }) {
  const det = value.detailer;
  const missing = catalog.nodes?.detailer === false;
  const stages = det?.stages ?? {};
  return (
    <div className="col gen-stage">
      <label className="row" style={{ gap: 6 }}>
        <input type="checkbox" checked={!!det} disabled={missing && !det} onChange={(e) => set({ detailer: e.target.checked ? DETAILER_DEFAULT : null })} />
        <strong>{t('gen.detailer')}</strong>
      </label>
      {missing && <span className="warn-text small">{t('gen.detailer_missing')}</span>}
      {det && (
        <>
          <div className="row" style={{ flexWrap: 'wrap', gap: 14 }}>
            {STAGES.map((stage) => (
              <label key={stage} className={stages[stage] === undefined ? 'row faint' : 'row'} style={{ gap: 4 }}>
                <input
                  type="checkbox"
                  checked={stages[stage] !== undefined}
                  onChange={(e) => {
                    const next = { ...stages };
                    if (e.target.checked) next[stage] = STAGE_DEFAULT[stage];
                    else delete next[stage];
                    set({ detailer: { ...det, stages: next } });
                  }}
                />
                {t(`gen.stage.${stage}`)}
                <input
                  type="number"
                  step={0.05}
                  min={0.05}
                  max={1}
                  style={{ width: 62 }}
                  disabled={stages[stage] === undefined}
                  value={stages[stage] ?? STAGE_DEFAULT[stage]}
                  onChange={(e) => set({ detailer: { ...det, stages: { ...stages, [stage]: Number(e.target.value) } } })}
                />
              </label>
            ))}
          </div>
          <Num label={t('gen.steps')} value={det.steps} onChange={(v) => set({ detailer: { ...det, steps: v ?? 20 } })} />
          <span className="faint small">{t('gen.detailer_hint')}</span>
        </>
      )}
    </div>
  );
}

function Num({ label, value, step = 1, placeholder, onChange }: { label: string; value?: number; step?: number; placeholder?: string; onChange: (value: number | undefined) => void }) {
  return (
    <label className="col gen-field">
      <span className="muted">{label}</span>
      <input type="number" step={step} style={{ width: 72 }} placeholder={placeholder} value={value ?? ''} onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))} />
    </label>
  );
}
