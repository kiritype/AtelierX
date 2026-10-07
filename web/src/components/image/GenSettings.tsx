import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
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
  // Custom nodes (#178): model patches in order, names to use when a node-pack sampler or scheduler is missing.
  patches?: Patch[];
  fallback?: { sampler?: string; scheduler?: string };
  missing?: 'ask' | 'skip';
};
export type Patch = { node: string; inputs: Record<string, PatchValue>; enabled?: boolean };
type PatchValue = number | string | boolean;
type PatchField = { type: 'INT' | 'FLOAT' | 'BOOLEAN' | 'STRING' | 'COMBO'; default?: PatchValue; min?: number; max?: number; step?: number; options?: string[]; optional?: boolean };
export type PatchNode = { label: string; module: string; inputs: Record<string, PatchField> };
// Schedulers the server draws with built-in nodes when ComfyUI does not list them.
const SCHEDULER_ALIASES = ['beta57'];

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
  patch_nodes?: Record<string, PatchNode>;
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
  const pick = (key: keyof GenerationSettings, label: string, options: string[], allowEmpty?: string, extra: string[] = []) => {
    const current = value[key] as string | undefined;
    // A name ComfyUI does not list (a node pack's sampler from a preset) stays visible, marked.
    const absent = current && !options.includes(current) && !extra.includes(current) ? [current] : [];
    return (
      <label className="col gen-field">
        <span className="muted">{label}</span>
        <select value={current ?? ''} onChange={(e) => set({ [key]: e.target.value || undefined })}>
          {allowEmpty !== undefined && <option value="">{allowEmpty}</option>}
          {options.map((o) => (
            <option key={o} value={o}>
              {base(o)}
            </option>
          ))}
          {extra
            .filter((o) => !options.includes(o))
            .map((o) => (
              <option key={o} value={o}>
                {t('gen.alias_option', { name: o })}
              </option>
            ))}
          {absent.map((o) => (
            <option key={o} value={o}>
              {t('gen.absent_option', { name: o })}
            </option>
          ))}
        </select>
      </label>
    );
  };

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
        {pick('scheduler', t('gen.scheduler'), c.schedulers, t('gen.default'), SCHEDULER_ALIASES)}
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
      <PatchFields value={value} set={set} catalog={c} />
    </div>
  );
}

// Custom nodes (#178): model patches built from the node's own input list, and the fallback names.
function PatchFields({ value, set, catalog }: { value: GenerationSettings; set: (patch: GenerationSettings) => void; catalog: Catalog }) {
  const nodes = catalog.patch_nodes ?? {};
  const patches = value.patches ?? [];
  const [adding, setAdding] = useState('');
  const [filter, setFilter] = useState('');
  const [open, setOpen] = useState(patches.length > 0 || !!value.fallback);
  const names = Object.keys(nodes)
    .filter((n) => !filter || `${n} ${nodes[n].label} ${nodes[n].module}`.toLowerCase().includes(filter.toLowerCase()))
    .sort((a, b) => nodes[a].label.localeCompare(nodes[b].label));
  const change = (n: number, patch: Partial<Patch>) => set({ patches: patches.map((p, i) => (i === n ? { ...p, ...patch } : p)) });
  const move = (n: number, by: number) => {
    const next = [...patches];
    const [item] = next.splice(n, 1);
    next.splice(n + by, 0, item);
    set({ patches: next });
  };
  const add = (name: string) => {
    const spec = nodes[name];
    const inputs: Record<string, PatchValue> = {};
    for (const [key, field] of Object.entries(spec.inputs)) if (!field.optional && field.default !== undefined) inputs[key] = field.default;
    set({ patches: [...patches, { node: name, inputs }] });
    setAdding('');
  };
  const samplerMissing = !!value.sampler && !catalog.samplers.includes(value.sampler);
  const schedulerMissing = !!value.scheduler && !catalog.schedulers.includes(value.scheduler) && !SCHEDULER_ALIASES.includes(value.scheduler);
  const fallback = value.fallback ?? {};
  const setFallback = (patch: { sampler?: string; scheduler?: string }) => {
    const next = { ...fallback, ...patch };
    set({ fallback: next.sampler || next.scheduler ? next : undefined });
  };
  return (
    <div className="col gen-stage">
      <button className="ghost row" style={{ gap: 6, justifyContent: 'flex-start' }} onClick={() => setOpen(!open)}>
        <span>{open ? '▾' : '▸'}</span>
        <strong>{t('gen.patches')}</strong>
        {patches.length > 0 && <span className="chip small">{patches.filter((p) => p.enabled !== false).length}</span>}
      </button>
      {(samplerMissing || schedulerMissing) && (
        <span className="warn-text small">{t('gen.pack_name_missing', { names: [samplerMissing && value.sampler, schedulerMissing && value.scheduler].filter(Boolean).join(', ') })}</span>
      )}
      {open && (
        <>
          <span className="faint small">{t('gen.patches_hint')}</span>
          {patches.map((patch, n) => {
            const spec = nodes[patch.node];
            return (
              <div key={n} className={patch.enabled === false ? 'col gen-patch faint' : 'col gen-patch'}>
                <div className="row" style={{ gap: 6 }}>
                  <input
                    type="checkbox"
                    checked={patch.enabled !== false}
                    aria-label={t('gen.patch_enabled')}
                    title={t('gen.patch_enabled')}
                    onChange={(e) => change(n, { enabled: e.target.checked ? undefined : false })}
                  />
                  <strong title={patch.node}>{spec?.label ?? patch.node}</strong>
                  {!spec && <span className="warn-text small">{t('gen.patch_missing', { name: patch.node })}</span>}
                  <span className="grow" />
                  <button className="ghost small" disabled={n === 0} onClick={() => move(n, -1)} aria-label={t('gen.move_up')}>
                    ↑
                  </button>
                  <button className="ghost small" disabled={n === patches.length - 1} onClick={() => move(n, 1)} aria-label={t('gen.move_down')}>
                    ↓
                  </button>
                  <button className="ghost small" onClick={() => set({ patches: patches.filter((_, i) => i !== n) })} aria-label={t('common.delete')}>
                    ×
                  </button>
                </div>
                {spec && (
                  <div className="row" style={{ flexWrap: 'wrap', alignItems: 'flex-end' }}>
                    {Object.entries(spec.inputs).map(([key, field]) => (
                      <PatchInput
                        key={key}
                        name={key}
                        field={field}
                        value={patch.inputs[key]}
                        onChange={(v) => {
                          const inputs = { ...patch.inputs };
                          if (v === undefined) delete inputs[key];
                          else inputs[key] = v;
                          change(n, { inputs });
                        }}
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
          {Object.keys(nodes).length > 0 ? (
            <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
              <input placeholder={t('gen.patch_search')} value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 160 }} />
              <select value={adding} onChange={(e) => setAdding(e.target.value)} style={{ maxWidth: 320 }}>
                <option value="">{t('gen.patch_choose', { n: names.length })}</option>
                {names.map((name) => (
                  <option key={name} value={name}>
                    {nodes[name].label === name ? name : `${nodes[name].label} (${name})`}
                  </option>
                ))}
              </select>
              <button disabled={!adding || patches.length >= 8} onClick={() => add(adding)}>
                {t('gen.add_patch')}
              </button>
            </div>
          ) : (
            <span className="faint small">{t('gen.no_patch_nodes')}</span>
          )}
          <div className="row" style={{ flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <span className="muted small" style={{ alignSelf: 'center' }}>
              {t('gen.fallback')}
            </span>
            <label className="col gen-field">
              <span className="muted">{t('gen.sampler')}</span>
              <select value={fallback.sampler ?? ''} onChange={(e) => setFallback({ sampler: e.target.value || undefined })}>
                <option value="">{t('gen.default')}</option>
                {catalog.samplers.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            </label>
            <label className="col gen-field">
              <span className="muted">{t('gen.scheduler')}</span>
              <select value={fallback.scheduler ?? ''} onChange={(e) => setFallback({ scheduler: e.target.value || undefined })}>
                <option value="">{t('gen.default')}</option>
                {catalog.schedulers.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </>
      )}
    </div>
  );
}

function PatchInput({ name, field, value, onChange }: { name: string; field: PatchField; value: PatchValue | undefined; onChange: (value: PatchValue | undefined) => void }) {
  const shown = value ?? field.default;
  if (field.type === 'BOOLEAN')
    return (
      <label className="row gen-field" style={{ gap: 4 }}>
        <input type="checkbox" checked={!!shown} onChange={(e) => onChange(e.target.checked)} />
        <span className="muted">{name}</span>
      </label>
    );
  return (
    <label className="col gen-field">
      <span className="muted">
        {name}
        {field.optional ? ` (${t('gen.optional')})` : ''}
      </span>
      {field.type === 'COMBO' ? (
        <select value={String(shown ?? '')} onChange={(e) => onChange(e.target.value)}>
          {(field.options ?? []).map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      ) : field.type === 'STRING' ? (
        <input value={String(value ?? '')} placeholder={field.default === undefined ? '' : String(field.default)} onChange={(e) => onChange(e.target.value === '' && field.optional ? undefined : e.target.value)} />
      ) : (
        <input
          type="number"
          style={{ width: 84 }}
          step={field.step ?? (field.type === 'INT' ? 1 : 0.01)}
          min={field.min}
          max={field.max}
          title={field.min !== undefined || field.max !== undefined ? `${field.min ?? ''} ~ ${field.max ?? ''}` : undefined}
          value={shown === undefined ? '' : Number(shown)}
          onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))}
        />
      )}
    </label>
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
