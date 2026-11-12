import { useId, useState } from 'react';
import { t } from '../../i18n';
import { MODEL_POOL_LIMIT, type ExplorerModel } from './styleExplorerDraft';

export default function ExplorerModels({ models, catalog, onChange }: {
  models: string[];
  catalog?: ExplorerModel[];
  onChange: (models: string[]) => void;
}) {
  const id = useId();
  const [query, setQuery] = useState('');
  const [picked, setPicked] = useState('');
  const added = new Set(models);
  const available = new Map(catalog?.map((model) => [model.id, model]));
  const term = query.trim().toLowerCase();
  const options = catalog?.filter((model) => !added.has(model.id) &&
    [model.name, model.id, model.type].some((value) => value?.toLowerCase().includes(term)));
  const next = options?.find((model) => model.id === picked);
  const atLimit = models.length >= MODEL_POOL_LIMIT;
  const missing = catalog && models.some((model) => !available.has(model));

  const label = ({ name, type }: ExplorerModel) => type ? `${name} (${type === 'dit' ? 'DiT' : 'SDXL'})` : name;

  return (
    <section className="col explorer-model-pool" aria-labelledby={id}>
      <strong id={id}>{t('style_explorer.model_candidates')}</strong>
      <p className="muted small">{t(models.length ? 'style_explorer.model_pool_hint' : 'style_explorer.model_base_hint')}</p>
      <div className="row explorer-material-add explorer-model-add">
        <input
          type="search"
          aria-label={t('style_explorer.search_models')}
          placeholder={t('style_explorer.search_models')}
          value={query}
          disabled={!catalog?.length || atLimit}
          onChange={(event) => {
            setQuery(event.target.value);
            setPicked('');
          }}
        />
        <select
          aria-label={t('style_explorer.choose_model')}
          value={next?.id ?? ''}
          disabled={!options?.length || atLimit}
          onChange={(event) => setPicked(event.target.value)}
        >
          <option value="">{t(term && !options?.length ? 'style_explorer.model_no_results' : 'style_explorer.choose_model')}</option>
          {options?.map((option) => <option key={option.id} value={option.id}>{label(option)}</option>)}
        </select>
        <button type="button" disabled={!next || atLimit} onClick={() => {
          if (!next) return;
          onChange([...models, next.id]);
          setPicked('');
          setQuery('');
        }}>
          {t('style_explorer.add_model')}
        </button>
      </div>
      {!catalog && <p className="muted small">{t('style_explorer.model_catalog_unavailable')}</p>}
      {catalog?.length === 0 && <p className="muted small">{t('style_explorer.model_catalog_empty')}</p>}
      {models.length > 0 && (
        <ul className="explorer-material-list" aria-labelledby={id}>
          {models.map((model) => {
            const option = available.get(model);
            const name = option ? label(option) : model;
            return (
              <li className="row" key={model}>
                <span className={catalog && !option ? 'warn-text' : undefined}>{name}</span>
                <button
                  type="button"
                  className="ghost"
                  aria-label={t('style_explorer.remove_material', { name })}
                  onClick={() => onChange(models.filter((entry) => entry !== model))}
                >×</button>
              </li>
            );
          })}
        </ul>
      )}
      {missing && <p className="warn-text small">{t('style_explorer.model_missing')}</p>}
      {atLimit && <p className="muted small">{t('style_explorer.model_pool_limit', { limit: MODEL_POOL_LIMIT })}</p>}
    </section>
  );
}
