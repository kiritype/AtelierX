import { useId, useState } from 'react';
import { t } from '../../i18n';
import {
  effectiveCount, findLora, loraKey, loraWeightLimit, parseNames, validWeight,
  type ExplorerLora, type MaterialGroup, type MaterialPool,
} from './styleExplorerDraft';

type Props = {
  pool: MaterialPool;
  service: string;
  catalog?: ExplorerLora[];
  loraLimit: number;
  onChange: (patch: Partial<MaterialPool>) => void;
  openSettings?: () => void;
};

export default function ExplorerMaterials({ pool, service, catalog, loraLimit, onChange, openSettings }: Props) {
  const id = useId();
  const [tagInput, setTagInput] = useState('');
  const [loraInput, setLoraInput] = useState('');
  const { tags, loras } = pool;
  const tagNames = new Set(tags.items);
  const nextTags = parseNames(tagInput).filter((name) => !tagNames.has(name));
  const tagTooLong = nextTags.some((name) => name.length > 500);
  const materialCount = tags.items.length + loras.items.length;
  const tooManyTags = materialCount + nextTags.length > 10_000;
  const canAddTags = nextTags.length > 0 && !tagTooLong && !tooManyTags;
  const loraKeys = new Set(loras.items.map(loraKey));
  const options = catalog?.filter((option) => !loraKeys.has(loraKey(option)));
  const nextLora = options?.find((option) => loraKey(option) === loraInput);
  const canAddLora = !!nextLora && materialCount < 10_000;
  const missingLoras = loras.items.some((lora) => !findLora(lora, catalog));
  const updateTags = (patch: Partial<MaterialGroup<string>>) => onChange({ tags: { ...tags, ...patch } });
  const updateLoras = (patch: Partial<MaterialGroup<ExplorerLora>>) => onChange({ loras: { ...loras, ...patch } });
  const addTags = () => {
    if (!canAddTags) return;
    updateTags({ items: [...tags.items, ...nextTags] });
    setTagInput('');
  };

  return (
    <section className="col explorer-materials" aria-labelledby={id}>
      <div className="col explorer-material-heading">
        <h4 id={id}>{t('style_explorer.materials')}</h4>
        <p className="muted small">{t('style_explorer.materials_hint')}</p>
      </div>
      <div className="explorer-material-panels">
        <section className="col explorer-material-panel" aria-labelledby={`${id}-tags`}>
          <h5 id={`${id}-tags`}>{t('style_explorer.tag')}</h5>
          <div className="row explorer-material-add">
            <textarea
              rows={1}
              aria-label={t('style_explorer.tag')}
              placeholder={t('style_explorer.tags_placeholder')}
              value={tagInput}
              onChange={(event) => setTagInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return;
                event.preventDefault();
                addTags();
              }}
            />
            <button type="button" disabled={!canAddTags} onClick={addTags}>{t('style_explorer.add_tags')}</button>
          </div>
          {tagTooLong && <p className="warn-text small">{t('style_explorer.tag_too_long')}</p>}
          {tooManyTags && <p className="warn-text small">{t('style_explorer.pool_full')}</p>}
          <ul className="explorer-material-list" aria-labelledby={`${id}-tags`}>
            {tags.items.map((name) => (
              <MaterialItem key={name} name={name} remove={() => updateTags({ items: tags.items.filter((item) => item !== name) })} />
            ))}
          </ul>
          <Ranges group={tags} maxWeight={10} onChange={updateTags} />
        </section>
        {service !== 'novelai' && (
          <section className="col explorer-material-panel" aria-labelledby={`${id}-loras`}>
            <h5 id={`${id}-loras`}>LoRA</h5>
            <div className="row explorer-material-add">
              <select
                aria-label={t('style_explorer.choose_lora')}
                value={loraInput}
                disabled={!options?.length || materialCount >= 10_000}
                onChange={(event) => setLoraInput(event.target.value)}
              >
                <option value="">{t('style_explorer.choose_lora')}</option>
                {options?.map((option) => <option key={loraKey(option)} value={loraKey(option)}>{option.name}</option>)}
              </select>
              <button
                type="button"
                disabled={!canAddLora}
                onClick={() => {
                  if (!nextLora) return;
                  const { name, id, trigger_words } = nextLora;
                  updateLoras({ items: [...loras.items, { name, id, trigger_words }] });
                  setLoraInput('');
                }}
              >
                {t('gen.add_lora')}
              </button>
            </div>
            {!catalog?.length && (
              <p className="muted small">
                {t(!catalog ? 'style_explorer.lora_catalog_unavailable'
                  : service === 'pixai' ? 'pixai.no_loras' : 'style_explorer.no_family_loras')}
                {openSettings && <> <button type="button" className="ghost small" onClick={openSettings}>{t('style_explorer.open_settings')}</button></>}
              </p>
            )}
            <ul className="explorer-material-list" aria-labelledby={`${id}-loras`}>
              {loras.items.map((lora) => {
                const registered = findLora(lora, catalog);
                const key = loraKey(lora);
                return <MaterialItem key={key} name={registered?.name ?? lora.name} unavailable={!registered}
                  remove={() => updateLoras({ items: loras.items.filter((item) => loraKey(item) !== key) })} />;
              })}
            </ul>
            {missingLoras && <p className="warn-text small">{t('style_explorer.lora_missing')}</p>}
            <Ranges group={loras} countLimit={loraLimit} maxWeight={loraWeightLimit(service)} onChange={updateLoras} />
          </section>
        )}
      </div>
    </section>
  );
}

function MaterialItem({ name, unavailable = false, remove }: { name: string; unavailable?: boolean; remove: () => void }) {
  return (
    <li className="row">
      <span className={unavailable ? 'warn-text' : undefined}>{name}</span>
      <button type="button" className="ghost" aria-label={t('style_explorer.remove_material', { name })} onClick={remove}>×</button>
    </li>
  );
}

function Ranges<T>({ group, countLimit, maxWeight, onChange }: {
  group: MaterialGroup<T>;
  countLimit?: number;
  maxWeight: number;
  onChange: (patch: Partial<MaterialGroup<T>>) => void;
}) {
  const { min, max, cap } = effectiveCount(group, countLimit);
  const invalidWeight = !validWeight(group, maxWeight);
  return (
    <div className="col explorer-material-ranges">
      <div>
        <fieldset>
          <legend>{t('style_explorer.per_image')}</legend>
          <div className="row">
            <label className="col">
              {t('style_explorer.count_min')}
              <input type="number" min={0} max={max} value={min} disabled={!cap}
                onChange={(event) => onChange({ countMin: Number(event.target.value) })} />
            </label>
            <label className="col">
              {t('style_explorer.count_max')}
              <input type="number" min={0} max={cap} value={max} disabled={!cap}
                onChange={(event) => onChange({ countMax: Number(event.target.value) })} />
            </label>
          </div>
        </fieldset>
        <fieldset>
          <legend>{t('style_explorer.weight_range')}</legend>
          <div className="row">
            <label className="col">
              {t('style_explorer.count_min')}
              <input type="number" step="any" min={0} max={maxWeight} value={group.weightMin ?? ''}
                onChange={(event) => onChange({ weightMin: event.target.value === '' ? undefined : event.target.valueAsNumber })} />
            </label>
            <label className="col">
              {t('style_explorer.count_max')}
              <input type="number" step="any" min={0} max={maxWeight} value={group.weightMax ?? ''}
                onChange={(event) => onChange({ weightMax: event.target.value === '' ? undefined : event.target.valueAsNumber })} />
            </label>
          </div>
        </fieldset>
      </div>
      {invalidWeight && <p className="warn-text small">{t('style_explorer.invalid_weight', { max: maxWeight })}</p>}
    </div>
  );
}
