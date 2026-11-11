import { useId, useState } from 'react';
import { t } from '../../i18n';
import type { ExplorerMaterial, ExplorerSelectionRules, ExplorerWeight } from '../../styleExplorerTypes';
import { findLora, materialCounts, materialKey, parseNames, randomWeight, type ExplorerLoraOption } from './styleExplorerDraft';

const roles = ['style', 'character', 'other'] as const;
const modes = ['always', 'candidate', 'exclude'] as const;
const weightModes = ['fixed', 'random'] as const;

const weightLimit = (service: string, kind: ExplorerMaterial['kind']) =>
  service === 'pixai' && kind === 'lora' ? 1 : 10;

export function validWeight(weight: ExplorerWeight, max: number) {
  const within = (value?: number) => value != null && Number.isFinite(value) && value >= 0 && value <= max;
  if (weight.mode === 'fixed') return within(weight.value);
  const { low, high, step } = weight;
  return low != null && high != null && step != null && within(low) && within(high)
    && Number.isFinite(step) && step > 0 && high >= low && (high - low) / step <= 10_000;
}

export function materialIsReady(material: ExplorerMaterial, service: string, loras?: ExplorerLoraOption[]) {
  if (service === 'novelai' && material.kind === 'lora') return false;
  return validWeight(material.weight, weightLimit(service, material.kind))
    && (material.kind === 'tag' || material.mode === 'exclude' || !!findLora(material, loras));
}

type Props = {
  materials: ExplorerMaterial[];
  rules: ExplorerSelectionRules;
  service: string;
  loras?: ExplorerLoraOption[];
  loraLimit: number;
  onMaterials: (materials: ExplorerMaterial[]) => void;
  onRules: (rules: Partial<ExplorerSelectionRules>) => void;
  openSettings?: () => void;
};

export default function ExplorerMaterials({ materials, rules, service, loras, loraLimit, onMaterials, onRules, openSettings }: Props) {
  const id = useId();
  const [tags, setTags] = useState('');
  const [loraKey, setLoraKey] = useState('');
  const supportsLoras = service !== 'novelai';
  const existing = new Set(materials.map(materialKey));
  const newLoras = loras?.filter((option) => !existing.has(materialKey({ kind: 'lora', ...option })));
  const newLora = newLoras?.find((option) => (option.id ?? option.name) === loraKey);
  const newTags = parseNames(tags).filter((name) => !existing.has(materialKey({ kind: 'tag', name })));
  const tagTooLong = newTags.some((name) => name.length > 500);
  const poolFull = materials.length >= 10_000;
  const tooManyTags = materials.length + newTags.length > 10_000;
  const tagCounts = materialCounts(materials, 'tag');
  const loraCounts = materialCounts(materials, 'lora');

  return (
    <section className="col explorer-materials" aria-labelledby={id}>
      <header className="col">
        <h4 id={id}>{t('style_explorer.materials')}</h4>
        <p className="muted">{t('style_explorer.materials_hint')}</p>
      </header>
      <div className="explorer-material-add">
        <div className="col">
          <label className="col">
            <strong>{t('style_explorer.tag')}</strong>
            <textarea
              rows={2}
              value={tags}
              placeholder={t('style_explorer.tags_placeholder')}
              onChange={(event) => setTags(event.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={!newTags.length || tagTooLong || tooManyTags}
            onClick={() => {
              onMaterials([...materials, ...newTags.map((name): ExplorerMaterial => ({
                name, kind: 'tag', role: 'style', mode: 'candidate', weight: randomWeight('tag'),
              }))]);
              setTags('');
            }}
          >
            {t('style_explorer.add_tags')}
          </button>
          {tagTooLong && <p className="warn-text small">{t('style_explorer.tag_too_long')}</p>}
          {tooManyTags && <p className="warn-text small">{t('style_explorer.pool_full')}</p>}
        </div>
        {supportsLoras && (
          <div className="col">
            <label className="col">
              <strong>LoRA</strong>
              <select value={loraKey} disabled={poolFull || !newLoras?.length} onChange={(event) => setLoraKey(event.target.value)}>
                <option value="">{t('style_explorer.choose_lora')}</option>
                {newLoras?.map((option) => (
                  <option key={option.id ?? option.name} value={option.id ?? option.name}>{option.name}</option>
                ))}
              </select>
            </label>
            {newLoras?.length ? (
              <button
                type="button"
                disabled={poolFull || !newLora}
                onClick={() => {
                  if (!newLora) return;
                  const { weight, ...option } = newLora;
                  onMaterials([...materials, {
                    ...option, kind: 'lora', role: 'style', mode: 'candidate', weight: { mode: 'fixed', value: weight ?? 0.8 },
                  }]);
                  setLoraKey('');
                }}
              >
                {t('gen.add_lora')}
              </button>
            ) : (
              <p className="muted small">
                {t(!loras ? 'style_explorer.lora_catalog_unavailable'
                  : loras.length ? 'style_explorer.lora_all_added'
                    : service === 'pixai' ? 'pixai.no_loras' : 'style_explorer.no_family_loras')}
                {openSettings && !loras?.length && (
                  <> <button type="button" className="ghost small" onClick={openSettings}>{t('style_explorer.open_settings')}</button></>
                )}
              </p>
            )}
          </div>
        )}
      </div>
      {!supportsLoras && <p className="muted small">{t('style_explorer.tags_only')}</p>}
      {materials.map((material) => {
        const option = material.kind === 'lora' ? findLora(material, loras) : undefined;
        const key = materialKey(material);
        return (
          <MaterialRow
            key={key}
            material={material}
            option={option}
            maxWeight={weightLimit(service, material.kind)}
            update={(patch) => onMaterials(materials.map((item) => materialKey(item) === key ? { ...item, ...patch } : item))}
            remove={() => onMaterials(materials.filter((item) => materialKey(item) !== key))}
          />
        );
      })}
      <div className="col explorer-material-counts">
        <p className="muted small">{t('style_explorer.counts_hint')}</p>
        <div className="explorer-material-add">
          <CountRange
            name={t('style_explorer.tag_count')}
            counts={tagCounts}
            min={rules.artist_min}
            max={rules.artist_max}
            changeMin={(artist_min) => onRules({ artist_min })}
            changeMax={(artist_max) => onRules({ artist_max })}
          />
          {supportsLoras && (
            <CountRange
              name={t('style_explorer.lora_count')}
              counts={loraCounts}
              min={rules.lora_min}
              max={rules.lora_max}
              limit={loraLimit}
              changeMin={(lora_min) => onRules({ lora_min })}
              changeMax={(lora_max) => onRules({ lora_max })}
            />
          )}
        </div>
      </div>
    </section>
  );
}

function MaterialRow({ material, option, maxWeight, update, remove }: {
  material: ExplorerMaterial;
  option?: ExplorerLoraOption;
  maxWeight: number;
  update: (patch: Partial<ExplorerMaterial>) => void;
  remove: () => void;
}) {
  const { kind, mode, role, weight } = material;
  const name = option?.name ?? material.name;
  const fixedValue = (weight.mode === 'fixed' ? weight.value : undefined) ?? option?.weight ?? 0.8;
  const invalidWeight = !validWeight(weight, maxWeight);
  return (
    <fieldset className="explorer-material-row">
      <legend>{kind === 'tag' ? t('style_explorer.tag_short') : 'LoRA'} · {name}</legend>
      <div className="explorer-material-controls">
        <label className="col">
          {t('style_explorer.role')}
          <select
            value={role}
            onChange={(event) => {
              const role = event.target.value as ExplorerMaterial['role'];
              update(role === 'character' ? { role, mode: 'always', weight: { mode: 'fixed', value: fixedValue } } : { role });
            }}
          >
            {roles.map((value) => <option key={value} value={value}>{t(`style_explorer.role_${value}`)}</option>)}
          </select>
        </label>
        <label className="col">
          {t('style_explorer.inclusion')}
          <select value={mode} onChange={(event) => update({ mode: event.target.value as ExplorerMaterial['mode'] })}>
            {modes.map((value) => <option key={value} value={value}>{t(`style_explorer.${value}`)}</option>)}
          </select>
        </label>
        <label className="col">
          {t('style_explorer.weight_mode')}
          <select
            value={weight.mode}
            onChange={(event) => update({
              weight: event.target.value === 'fixed' ? { mode: 'fixed', value: fixedValue } : randomWeight(kind),
            })}
          >
            {weightModes.map((value) => <option key={value} value={value}>{t(`style_explorer.weight_${value}`)}</option>)}
          </select>
        </label>
        {weight.mode === 'fixed' ? (
          <NumberField label={t('style_explorer.weight_value')} value={weight.value} max={maxWeight}
            onChange={(value) => update({ weight: { mode: 'fixed', value } })} />
        ) : (
          <>
            <NumberField label={t('style_explorer.weight_low')} value={weight.low} max={maxWeight}
              onChange={(low) => update({ weight: { ...weight, low } })} />
            <NumberField label={t('style_explorer.weight_high')} value={weight.high} max={maxWeight}
              onChange={(high) => update({ weight: { ...weight, high } })} />
            <NumberField label={t('style_explorer.weight_step')} value={weight.step}
              onChange={(step) => update({ weight: { ...weight, step } })} />
          </>
        )}
        <button type="button" className="ghost" aria-label={t('style_explorer.remove_material', { name })} onClick={remove}>×</button>
      </div>
      {kind === 'lora' && (
        <label className="col explorer-trigger-field">
          {t('style_explorer.trigger_words')}
          <input value={material.trigger_words ?? ''} maxLength={500} onChange={(event) => update({ trigger_words: event.target.value })} />
        </label>
      )}
      {kind === 'lora' && !option && <p className="warn-text small">{t('style_explorer.lora_missing')}</p>}
      {invalidWeight && <p className="warn-text small">{t('style_explorer.invalid_weight', { max: maxWeight })}</p>}
    </fieldset>
  );
}

function NumberField({ label, value, max, onChange }: {
  label: string; value?: number; max?: number; onChange: (value: number | undefined) => void;
}) {
  return (
    <label className="col">
      {label}
      <input type="number" step="any" min={0} max={max} value={value ?? ''}
        onChange={(event) => onChange(event.target.value === '' ? undefined : event.target.valueAsNumber)} />
    </label>
  );
}

function CountRange({ name, counts, min, max, limit = counts.available, changeMin, changeMax }: {
  name: string;
  counts: { always: number; available: number };
  min: number;
  max: number;
  limit?: number;
  changeMin: (value: number) => void;
  changeMax: (value: number) => void;
}) {
  const ceiling = Math.min(limit, counts.available);
  const over = counts.always > ceiling;
  return (
    <fieldset className="explorer-material-range">
      <legend>{name}</legend>
      <div className="row">
        <label className="col">
          {t('style_explorer.count_min')}
          <input type="number" min={counts.always} max={max} value={min} disabled={over || ceiling === counts.always}
            onChange={(event) => changeMin(Number(event.target.value))} />
        </label>
        <label className="col">
          {t('style_explorer.count_max')}
          <input type="number" min={counts.always} max={ceiling} value={max} disabled={over || ceiling === counts.always}
            onChange={(event) => changeMax(Number(event.target.value))} />
        </label>
        <span className="muted small">
          {t('style_explorer.count_summary', counts)}
        </span>
      </div>
      {over && <p className="warn-text small">{t('style_explorer.always_limit', { limit })}</p>}
    </fieldset>
  );
}
