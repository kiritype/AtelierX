import { t } from '../../i18n';
import GenSettings, { type GenerationSettings } from './GenSettings';
import NovelAISettings from './NovelAISettings';
import PixAISettings from './PixAISettings';
import ExplorerMaterials from './ExplorerMaterials';
import ExplorerModels from './ExplorerModels';
import { SERVICE_NAMES, type SettingsSection } from './serviceSettings';
import type { ExplorerCapabilities } from '../../styleExplorerTypes';
import { materialPool, settingsKey, switchContext, type ExplorerDraft, type ExplorerLora, type ExplorerModel } from './styleExplorerDraft';

export default function ExplorerSetup({
  draft: d,
  setDraft,
  capabilities,
  loras,
  models,
  modelCatalog,
  loraLimit,
  openSettings,
}: {
  draft: ExplorerDraft;
  setDraft: (d: ExplorerDraft) => void;
  capabilities?: ExplorerCapabilities;
  loras?: ExplorerLora[];
  models: string[];
  modelCatalog?: ExplorerModel[];
  loraLimit: number;
  openSettings?: () => void;
}) {
  const set = (change: Partial<ExplorerDraft>) => setDraft({ ...d, ...change });
  const key = settingsKey(d);
  const settings = d.settings[key] ?? {};
  const pool = materialPool(d);
  const hasModelCatalog = d.service === 'comfyui' || d.service === 'pixai';
  const modelCount = models.length;
  const update = (value: Record<string, unknown>) => set({ settings: { ...d.settings, [key]: value } });
  const providerSettings = (section: SettingsSection) => {
    if (d.service === 'novelai') return <NovelAISettings value={settings} onChange={update} section={section} />;
    if (d.service === 'pixai') return <PixAISettings value={settings} onChange={update} section={section} showLoras={false} modelCandidates={models} />;
    return (
      <GenSettings
        value={settings as GenerationSettings}
        onChange={(value) => update(value as Record<string, unknown>)}
        section={section}
        showLoras={false}
      />
    );
  };

  return (
    <div className="col explorer-setup">
      <p className="faint">{t('style_explorer.setup_about')}</p>
      <label className="col">
        <span>{t('style_explorer.name')}</span>
        <input maxLength={200} value={d.name} onChange={(event) => set({ name: event.target.value })} />
      </label>
      <section className="col explorer-context" aria-label={t('style_explorer.context')}>
        <div className="row">
          {['novelai', 'pixai', 'comfyui'].map((service) => (
            <button
              type="button"
              key={service}
              className={d.service === service ? 'selected' : 'ghost'}
              aria-pressed={d.service === service}
              onClick={() => setDraft(switchContext(d, { service }))}
            >
              {SERVICE_NAMES[service]}
            </button>
          ))}
        </div>
        {capabilities?.services.find((service) => service.id === d.service)?.enabled === false && (
          <p className="warn-text">
            {t('style_explorer.service_unavailable')}{' '}
            <button type="button" onClick={openSettings}>{t('style_explorer.open_settings')}</button>
          </p>
        )}
        {d.service === 'comfyui' && (
          <div className="row">
            {['anima', 'sdxl'].map((family) => (
              <button
                type="button"
                key={family}
                className={d.family === family ? 'selected' : 'ghost'}
                aria-pressed={d.family === family}
                onClick={() => setDraft(switchContext(d, { family }))}
              >
                {family === 'anima' ? 'Anima' : 'SDXL'}
              </button>
            ))}
            <button type="button" disabled>
              MOSS · {t('style_explorer.coming')}
            </button>
          </div>
        )}
        {(!hasModelCatalog || modelCount === 0) && providerSettings('model')}
        {hasModelCatalog ? (
          <ExplorerModels
            key={key}
            models={models}
            catalog={modelCatalog}
            onChange={(models) => set({ models })}
          />
        ) : (
          <details>
            <summary>
              {t('style_explorer.model_candidates')} · {t(modelCount === 0
                ? 'style_explorer.model_base'
                : modelCount === 1 ? 'style_explorer.model_one' : 'style_explorer.model_many', { count: modelCount })}
            </summary>
            <label className="col">
              <span>{t('style_explorer.models')}</span>
              <textarea rows={2} value={typeof d.models === 'string' ? d.models : models.join('\n')}
                onChange={(event) => set({ models: event.target.value })} />
            </label>
          </details>
        )}
      </section>
      <div className="explorer-prompts">
        {(['positive', 'negative'] as const).map((name) => (
          <label className="col" key={name}>
            <span>{t(`style_explorer.${name}`)}</span>
            <textarea rows={3} value={d[name]} onChange={(event) => set({ [name]: event.target.value })} />
          </label>
        ))}
      </div>
      <ExplorerMaterials
        key={key}
        pool={pool}
        service={d.service}
        family={d.family}
        catalog={loras}
        loraLimit={loraLimit}
        onChange={(change) => set({ materialPools: { ...d.materialPools, [key]: { ...pool, ...change } } })}
        openSettings={openSettings}
      />
      <details className="explorer-generation">
        <summary>{t('style_explorer.settings')}</summary>
        <label className="col">
          <span>{t('style_explorer.seed')}</span>
          <input type="number" min={-1} max={d.service === 'pixai' ? 2 ** 31 - 1 : 2 ** 32 - 1} value={d.seed} onChange={(event) => set({ seed: Number(event.target.value) })} />
        </label>
        {providerSettings('parameters')}
      </details>
      <div className="row explorer-run-fields">
        <label className="col">
          {t('style_explorer.count')}
          <input
            type="number"
            min={2}
            max={capabilities?.max_batch ?? 16}
            value={d.count}
            onChange={(event) => set({ count: Number(event.target.value) })}
          />
        </label>
        <label className="col">
          {t('style_explorer.budget')}
          <input
            type="number"
            min={2}
            max={capabilities?.max_budget ?? 200}
            value={d.budget}
            onChange={(event) => set({ budget: Number(event.target.value) })}
          />
        </label>
      </div>
    </div>
  );
}
