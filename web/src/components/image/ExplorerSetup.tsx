import { t } from '../../i18n';
import GenSettings, { type GenerationSettings } from './GenSettings';
import NovelAISettings from './NovelAISettings';
import PixAISettings from './PixAISettings';
import type { ExplorerCapabilities } from '../../styleExplorerTypes';
import { effectiveRules, parseArtists, settingsKey, switchContext, type ExplorerDraft } from './styleExplorerDraft';
export default function ExplorerSetup({
  draft: d,
  setDraft,
  capabilities: c,
  openSettings,
}: {
  draft: ExplorerDraft;
  setDraft: (d: ExplorerDraft) => void;
  capabilities?: ExplorerCapabilities;
  openSettings?: () => void;
}) {
  const set = (change: Partial<ExplorerDraft>) => setDraft({ ...d, ...change });
  const key = settingsKey(d),
    settings = d.settings[key] ?? {};
  const update = (value: Record<string, unknown>) => set({ settings: { ...d.settings, [key]: value } });
  const field = (name: 'name' | 'positive' | 'negative' | 'models', multiline = false) => (
    <label className="col">
      <span>{t(`style_explorer.${name}`)}</span>
      {multiline ? (
        <textarea rows={3} value={d[name]} onChange={(e) => set({ [name]: e.target.value })} />
      ) : (
        <input value={d[name]} onChange={(e) => set({ [name]: e.target.value })} />
      )}
    </label>
  );
  return (
    <div className="col explorer-setup">
      <p className="faint">{t('style_explorer.setup_about')}</p>
      {field('name')}
      <div className="row">
        {['novelai', 'pixai', 'comfyui'].map((service) => (
          <button
            type="button"
            key={service}
            className={d.service === service ? 'selected' : 'ghost'}
            onClick={() => setDraft(switchContext(d, { service }))}
          >
            {{ novelai: 'NovelAI', pixai: 'PixAI', comfyui: 'ComfyUI' }[service]}
          </button>
        ))}
      </div>
      {c?.services.find((s) => s.id === d.service)?.enabled === false && (
        <p className="warn-text">
          {t('style_explorer.service_unavailable')}{' '}
          <button type="button" onClick={openSettings}>
            {t('style_explorer.open_settings')}
          </button>
        </p>
      )}
      {d.service === 'comfyui' && (
        <div className="row">
          {['anima', 'sdxl'].map((family) => (
            <button
              type="button"
              key={family}
              className={d.family === family ? 'selected' : 'ghost'}
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
      {field('positive', true)}
      {field('negative', true)}
      <label className="col">
        <span>{t('style_explorer.seed')}</span>
        <input type="number" value={d.seed} onChange={(e) => set({ seed: Number(e.target.value) })} />
      </label>
      <details open>
        <summary>{t('style_explorer.settings')}</summary>
        <p className="faint">{t('style_explorer.fixed_settings')}</p>
        {d.service === 'comfyui' ? (
          <GenSettings
            value={settings as GenerationSettings}
            onChange={(v) =>
              v.family && v.family !== d.family
                ? setDraft(switchContext(d, { family: v.family }))
                : update(v as Record<string, unknown>)
            }
          />
        ) : d.service === 'novelai' ? (
          <NovelAISettings value={settings} onChange={update} />
        ) : (
          <PixAISettings value={settings} onChange={update} />
        )}
      </details>
      <label className="col">
        <span>{t('style_explorer.artists')}</span>
        <textarea
          rows={4}
          value={d.pool}
          onChange={(e) =>
            set({
              pool: e.target.value,
              artists: parseArtists(e.target.value, d.artists),
            })
          }
        />
      </label>
      {d.artists.map((artist, index) => (
        <label className="row" key={artist.name}>
          <span className="grow">{artist.name}</span>
          <select
            value={artist.mode}
            onChange={(e) =>
              set({
                artists: d.artists.map((a, i) => (i === index ? { ...a, mode: e.target.value as typeof a.mode } : a)),
              })
            }
          >
            {['always', 'candidate', 'exclude'].map((mode) => (
              <option key={mode} value={mode}>
                {t(`style_explorer.${mode}`)}
              </option>
            ))}
          </select>
        </label>
      ))}
      <p className="faint">{t('style_explorer.lora_pool')}</p>
      <details>
        <summary>{t('style_explorer.advanced')}</summary>
        {field('models', true)}
        <div className="explorer-rules">
          {Object.entries(effectiveRules(d)).map(([key, value]) => (
            <label className="col" key={key}>
              <span>{t(`style_explorer.${key}`)}</span>
              <input
                type="number"
                step={key.endsWith('min') || key.endsWith('max') ? 1 : 0.1}
                min={0}
                value={value}
                onChange={(e) => set({ rules: { ...d.rules, [key]: Number(e.target.value) } })}
              />
            </label>
          ))}
        </div>
      </details>
      <div className="row">
        <label className="col">
          {t('style_explorer.count')}
          <input
            type="number"
            min={2}
            max={c?.max_batch ?? 16}
            value={d.count}
            onChange={(e) => set({ count: Number(e.target.value) })}
          />
        </label>
        <label className="col">
          {t('style_explorer.budget')}
          <input
            type="number"
            min={2}
            max={c?.max_budget ?? 200}
            value={d.budget}
            onChange={(e) => set({ budget: Number(e.target.value) })}
          />
        </label>
      </div>
    </div>
  );
}
