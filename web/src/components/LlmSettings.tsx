import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { ApiError, get, post, put } from '../api';
import { t, tm } from '../i18n';
import { useToast } from './Toasts';
import { LLM_PRESETS, newProvider, usesLocalGpu, vertexUrl } from './llmPresets';
import UsageReport from './UsageReport';

// A model's limits in tokens; ``context_source`` says where the length came from (03-llm: 모델 맥락 길이).
type Limits = { context?: number | null; max_output?: number | null; context_source?: 'manual' | 'service' | 'table' | null };
type Provider = { name: string; type: string; preset?: string; vertex_project?: string; vertex_location?: string; base_url?: string; key?: string | null; trusted?: boolean; local_gpu?: boolean; default_model?: string | null; models?: Record<string, Limits> };
type TaskSetting = { provider?: string; model?: string; params?: { temperature?: number } };
type Doc = { schema_version: number; providers: Record<string, Provider>; tasks: Record<string, TaskSetting>; context_cap?: number };
type ModelInfo = { context: number | null; max_output: number | null; source: 'service' | 'table' | null };

const tokens = (value: string) => {
  const n = Math.round(Number(value));
  return value.trim() && Number.isFinite(n) && n > 0 ? n : null;
};

const TASKS = ['agent', 'chat_test', 'compression', 'authoring', 'image_prompt', 'jsx_prompt', 'consistency', 'image_review'] as const;
const DEFAULT_TEMPERATURE: Record<string, number> = { compression: 0.3, image_prompt: 0.2, jsx_prompt: 0.4, authoring: 0.7, consistency: 0, chat_test: 0.8, image_review: 0, agent: 0.5 };

// 03-llm: 연결 목록, 연결 시험(모델 목록), 작업별 기본 모델.
export default function LlmSettings() {
  const qc = useQueryClient();
  const toast = useToast();
  const query = useQuery<Doc>({ queryKey: ['providers'], queryFn: () => get('/api/providers') });
  const [doc, setDoc] = useState<Doc | null>(null);
  const [models, setModels] = useState<Record<string, string[]>>({});
  const [status, setStatus] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [presetId, setPresetId] = useState('ollama');
  const vault = useQuery<{ name: string; kind: string; masked: string }[]>({ queryKey: ['vault'], queryFn: () => get('/api/vault') });
  // Keys typed into a connection card; "Save" stores them in the vault (encrypted) and links them to the connection.
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [changingKey, setChangingKey] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (query.data && !dirty) setDoc(query.data);
  }, [query.data, dirty]);

  async function test(id: string, responseTest = false) {
    setBusy(b => ({ ...b, [id]: true }));
    setStatus((s) => ({ ...s, [id]: t('llm.testing') }));
    try {
      if (responseTest) {
        await post(`/api/providers/${id}/probe`);
        setStatus((s) => ({ ...s, [id]: t('llm.probe_ok') }));
        return;
      }
      const result = await get<{ models: string[] }>(`/api/providers/${id}/models`);
      setModels((m) => ({ ...m, [id]: result.models }));
      setStatus((s) => ({ ...s, [id]: doc?.providers[id]?.type === 'vertex_openai' ? t('llm.manual_catalog') : t('llm.ok', { n: result.models.length }) }));
    } catch (err) {
      setStatus((s) => ({ ...s, [id]: err instanceof ApiError ? tm(err.msg) : String(err) }));
    } finally {
      setBusy(b => ({ ...b, [id]: false }));
    }
  }



  if (!doc) return null;
  const change = (next: Doc) => {
    setDoc(next);
    setDirty(true);
  };
  const setProvider = (id: string, patch: Partial<Provider>) => {
    const next = { ...doc.providers[id], ...patch };
    if (next.preset === 'vertex') next.base_url = vertexUrl(next.vertex_project ?? '', next.vertex_location ?? '');
    setStatus(s => ({ ...s, [id]: '' }));
    if ('base_url' in patch || 'key' in patch || 'vertex_project' in patch || 'vertex_location' in patch) setModels(m => ({ ...m, [id]: [] }));
    change({ ...doc, providers: { ...doc.providers, [id]: next } });
  };
  const setTask = (task: string, patch: Partial<TaskSetting>) => change({ ...doc, tasks: { ...doc.tasks, [task]: { ...doc.tasks[task], ...patch } } });
  // The models a connection is used with: its default and every task that names one of its models.
  const usedModels = (id: string) =>
    [...new Set([doc.providers[id]?.default_model, ...Object.values(doc.tasks).filter((s) => (s.provider ?? 'local') === id).map((s) => s.model)])].filter(
      (m): m is string => !!m,
    );
  const setLimits = (id: string, model: string, patch: Limits) =>
    setProvider(id, { models: { ...doc.providers[id].models, [model]: { ...doc.providers[id].models?.[model], ...patch } } });

  // Ask the service (else the known-model table) for each model's context length. The values go into the form; Save keeps them.
  async function readLimits(id: string) {
    setBusy((b) => ({ ...b, [id]: true }));
    let next = { ...(doc!.providers[id].models ?? {}) };
    let found = 0;
    const list = usedModels(id);
    try {
      for (const model of list) {
        const info = await get<ModelInfo>(`/api/providers/${id}/model-info?model=${encodeURIComponent(model)}`);
        if (!info.context) continue;
        next = { ...next, [model]: { ...next[model], context: info.context, max_output: info.max_output ?? next[model]?.max_output ?? null, context_source: info.source } };
        found += 1;
      }
      setProvider(id, { models: next });
      setStatus((s) => ({ ...s, [id]: t('llm.context_read_done', { found, n: list.length }) }));
    } catch (err) {
      setStatus((s) => ({ ...s, [id]: err instanceof ApiError ? tm(err.msg) : String(err) }));
    } finally {
      setBusy((b) => ({ ...b, [id]: false }));
    }
  }

  const modelOptions = (id: string, current?: string | null) => {
    const list = models[id] ?? [];
    return current && !list.includes(current) ? [current, ...list] : list;
  };

  async function save() {
    try {
      let next = doc!;
      for (const [id, value] of Object.entries(keys)) {
        if (!value.trim() || !next.providers[id]) continue;
        // Never overwrite an entry another connection also uses: then this connection gets a new entry of its own.
        const name = keyEntryName(id, next.providers, (vault.data ?? []).map((v) => v.name));
        await post('/api/vault', {
          name,
          kind: next.providers[id].type === 'vertex_openai' ? 'service_token' : 'llm_api_key',
          value: value.trim(),
          note: next.providers[id].name,
        });
        next = { ...next, providers: { ...next.providers, [id]: { ...next.providers[id], key: `secret:${name}` } } };
      }
      const saved = await put<Doc>('/api/providers', next);
      qc.setQueryData(['providers'], saved);
      qc.invalidateQueries({ queryKey: ['vault'] });
      setKeys({});
      setChangingKey({});
      setDirty(false);
      toast({ text: t('common.saved') });
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    }
  }

  return (
    <div className="col" style={{ maxWidth: 820 }}>
      <p className="faint">{t('settings.llm_note')}</p>
      <div className="section-title">{t('llm.connections')}</div>
      {Object.entries(doc.providers).map(([id, provider]) => (
        <div key={id} className="col llm-provider">
          <div className="row wrap">
            <label className="col">{t('llm.connection_name')}<input style={{ width: 160 }} value={provider.name} onChange={(e) => setProvider(id, { name: e.target.value })} /></label>
            {provider.type === 'mock' ? (
              <span className="faint grow">{t('llm.mock')}</span>
            ) : (
              <label className="col grow">{t('llm.base_url')}<input className="mono" readOnly={provider.preset === 'vertex'} placeholder={provider.preset === 'vertex' ? t('llm.vertex_generated') : 'https://…'} value={provider.base_url ?? ''} onChange={(e) => setProvider(id, { base_url: e.target.value })} /></label>
            )}
            <button disabled={dirty || busy[id]} onClick={() => test(id)}>{t('llm.catalog')}</button>
            <button disabled={dirty || busy[id] || !provider.default_model} onClick={() => test(id, true)}>{t('llm.probe')}</button>
            {id !== 'local' && (
              <button
                className="danger"
                onClick={() => {
                  if (!confirm(t('llm.delete_confirm', { name: provider.name }))) return;
                  const providers = { ...doc.providers };
                  delete providers[id];
                  const tasks = Object.fromEntries(Object.entries(doc.tasks).filter(([, v]) => v.provider !== id));
                  change({ ...doc, providers, tasks });
                }}
              >
                {t('common.delete')}
              </button>
            )}
          </div>
          {provider.preset && <span className="faint">{LLM_PRESETS.find(p => p.id === provider.preset)?.name}</span>}
          {provider.preset === 'vertex' && <div className="row">
            <label className="col">{t('llm.vertex_project')}<input value={provider.vertex_project ?? ''} placeholder="my-project-123" onChange={e => setProvider(id, { vertex_project: e.target.value.trim() })} /></label>
            <label className="col">{t('llm.vertex_location')}<input value={provider.vertex_location ?? ''} placeholder="global / us-central1" onChange={e => setProvider(id, { vertex_location: e.target.value.trim() })} /></label>
          </div>}
          {provider.type === 'vertex_openai' && <p className="faint">{t('llm.vertex_help')}</p>}
          {provider.preset === 'gemini' && <p className="faint">{t('llm.gemini_help')}</p>}
          {provider.type !== 'mock' && (
            <div className="row wrap">
              <span className="muted">{provider.type === 'vertex_openai' ? t('llm.oauth_token') : t('llm.key')}</span>
              <KeyField
                provider={provider}
                vault={vault.data ?? []}
                typed={keys[id] ?? ''}
                changing={!!changingKey[id]}
                onType={(value) => {
                  setKeys((k) => ({ ...k, [id]: value }));
                  setDirty(true);
                }}
                onChange={(on) => {
                  setChangingKey((c) => ({ ...c, [id]: on }));
                  if (!on) setKeys((k) => ({ ...k, [id]: '' }));
                }}
                onPick={(name) => {
                  setKeys((k) => ({ ...k, [id]: '' }));
                  setChangingKey((c) => ({ ...c, [id]: false }));
                  setProvider(id, { key: name ? `secret:${name}` : null });
                }}
              />
              <label className="row" style={{ gap: 4 }}>
                <input type="checkbox" checked={!!provider.trusted} onChange={(e) => setProvider(id, { trusted: e.target.checked })} />
                {t('llm.trusted')}
              </label>
              <label className="row" style={{ gap: 4 }} title={t('llm.local_gpu_help')}>
                <input type="checkbox" checked={usesLocalGpu(provider)} onChange={(e) => setProvider(id, { local_gpu: e.target.checked })} />
                {t('llm.local_gpu')}
              </label>
            </div>
          )}
          {provider.type !== 'mock' && <p className="faint">{t('llm.credentials_help')}</p>}
          <div className="row wrap">
            <span className="muted">{t('llm.default_model')}</span>
            <input aria-label={t('llm.default_model')} list={`models-${id}`} value={provider.default_model ?? ''} placeholder={t('llm.model_placeholder')} onChange={(e) => setProvider(id, { default_model: e.target.value || null })} />
            <datalist id={`models-${id}`}>{modelOptions(id, provider.default_model).map(m => <option key={m} value={m} />)}</datalist>
            <button onClick={() => change({ ...doc, tasks: Object.fromEntries(TASKS.map(task => [task, { ...doc.tasks[task], provider: id, model: undefined }])) })}>{t('llm.all_tasks')}</button>
            <span className="faint grow">{status[id]}</span>
          </div>
          {usedModels(id).length > 0 && (
            <div className="col" style={{ gap: 4 }}>
              <div className="row wrap">
                <span className="muted" title={t('llm.context_help')}>{t('llm.context_title')}</span>
                <button disabled={dirty || busy[id]} onClick={() => readLimits(id)}>{t('llm.context_read')}</button>
              </div>
              {usedModels(id).map((model) => {
                const limits = provider.models?.[model] ?? {};
                return (
                  <div key={model} className="row wrap">
                    <code>{model}</code>
                    <input
                      type="number"
                      min={1}
                      style={{ width: 120 }}
                      aria-label={t('llm.context_length', { model })}
                      value={limits.context ?? ''}
                      placeholder={t('llm.context_unknown')}
                      onChange={(e) => setLimits(id, model, { context: tokens(e.target.value), context_source: 'manual' })}
                    />
                    <span className="faint small">
                      {limits.context ? t(`llm.context_source.${limits.context_source ?? 'manual'}`) : t('llm.context_source.none')}
                      {limits.max_output ? ` · ${t('llm.max_output', { n: limits.max_output.toLocaleString() })}` : ''}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      ))}
      <p className="faint">{dirty ? t('llm.save_before_test') : t('llm.manual_help')}</p>
      <p className="faint">{t('llm.probe_notice')}</p>
      <div className="row">
        <label>{t('llm.preset')} <select value={presetId} onChange={e => setPresetId(e.target.value)}>{LLM_PRESETS.map(p => <option key={p.id} value={p.id}>{p.id === 'custom' ? t('llm.custom_preset') : p.name}</option>)}</select></label>
        <button onClick={() => {
          let n = 1;
          while (doc.providers[`remote${n}`]) n++;
          change({ ...doc, providers: { ...doc.providers, [`remote${n}`]: newProvider(presetId) } });
        }}>{t('llm.add')}</button>
      </div>
      <p className="faint">{t('llm.external_note')}</p>
      <div className="section-title">{t('llm.tasks')}</div>
      <table className="plain">
        <tbody>
          {TASKS.map((task) => {
            const setting = doc.tasks[task] ?? {};
            const providerId = setting.provider ?? 'local';
            return (
              <tr key={task}>
                <td>{t(`llm.task.${task}`)}</td>
                <td>
                  <select value={providerId} onChange={(e) => setTask(task, { provider: e.target.value, model: undefined })}>
                    {Object.entries(doc.providers).map(([id, p]) => (
                      <option key={id} value={id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input list={`models-${providerId}`} value={setting.model ?? ''} placeholder={t('llm.use_default', { model: doc.providers[providerId]?.default_model ?? '—' })} onChange={(e) => setTask(task, { model: e.target.value || undefined })} />
                </td>
                <td>
                  <label className="row" style={{ gap: 4 }} title={t('llm.temperature_help')}>
                    <span className="faint">{t('llm.temperature')}</span>
                    <input
                      type="number"
                      step={0.1}
                      min={0}
                      max={2}
                      style={{ width: 64 }}
                      value={setting.params?.temperature ?? DEFAULT_TEMPERATURE[task]}
                      onChange={(e) => setTask(task, { params: { ...setting.params, temperature: Number(e.target.value) } })}
                    />
                  </label>
                </td>
                <td>
                  {setting.params?.temperature !== undefined && setting.params.temperature !== DEFAULT_TEMPERATURE[task] && (
                    <button
                      className="ghost small"
                      title={t('llm.temperature_default', { n: DEFAULT_TEMPERATURE[task] })}
                      onClick={() => setTask(task, { params: { ...setting.params, temperature: undefined } })}
                    >
                      {t('llm.temperature_reset')}
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="faint">{t('llm.temperature_note')}</p>
      <label className="row wrap" title={t('llm.context_cap_help')}>
        <span className="muted">{t('llm.context_cap')}</span>
        <input
          type="number"
          min={1024}
          step={1024}
          style={{ width: 120 }}
          value={doc.context_cap ?? ''}
          placeholder="131072"
          onChange={(e) => change({ ...doc, context_cap: tokens(e.target.value) ?? undefined })}
        />
        <span className="faint small">{t('llm.context_cap_help')}</span>
      </label>
      <p className="faint">{t('llm.reasoning_note')}</p>
      <UsageReport providerName={(id) => doc.providers[id]?.name ?? id} />
      <div>
        <button className="primary" disabled={!dirty} onClick={save}>
          {t('common.save')}
        </button>
      </div>
    </div>
  );
}

// A connection's key: the stored one masked with change/remove, or a field to paste a new one. Keys stored for other
// connections can still be picked, for a key shared by several connections.
function KeyField({
  provider,
  vault,
  typed,
  changing,
  onType,
  onChange,
  onPick,
}: {
  provider: Provider;
  vault: { name: string; kind: string; masked: string }[];
  typed: string;
  changing: boolean;
  onType: (value: string) => void;
  onChange: (on: boolean) => void;
  onPick: (name: string | null) => void;
}) {
  const name = provider.key ? String(provider.key).replace(/^secret:/, '') : '';
  const stored = vault.find((v) => v.name === name);
  if (stored && !changing) {
    return (
      <>
        <code>{stored.masked}</code>
        <span className="faint small">{stored.name}</span>
        <button onClick={() => onChange(true)}>{t('llm.key_change')}</button>
        <button className="ghost" onClick={() => onPick(null)}>{t('llm.key_remove')}</button>
      </>
    );
  }
  return (
    <>
      {name && !stored && <span className="warn-text">{t('llm.key_missing', { name })}</span>}
      <input
        type="password"
        className="grow"
        style={{ minWidth: 200 }}
        autoComplete="off"
        placeholder={t('llm.key_paste')}
        value={typed}
        onChange={(e) => onType(e.target.value)}
      />
      {vault.length > 0 && (
        <select aria-label={t('llm.key_pick')} value="" onChange={(e) => e.target.value && onPick(e.target.value)}>
          <option value="">{t('llm.key_pick')}</option>
          {vault.map((v) => (
            <option key={v.name} value={v.name}>
              {v.name} ({v.masked})
            </option>
          ))}
        </select>
      )}
      {changing && <button className="ghost" onClick={() => onChange(false)}>{t('common.cancel')}</button>}
    </>
  );
}

// The vault entry a connection's new key goes into: `llm-<id>` (or `llm-<id>-2` …), reused only when no other connection
// refers to it and it is not someone else's entry already.
export function keyEntryName(id: string, providers: Record<string, { key?: string | null }>, stored: string[]): string {
  const mine = providers[id]?.key ?? null;
  const taken = (name: string) =>
    Object.entries(providers).some(([other, p]) => other !== id && p.key === `secret:${name}`) ||
    (stored.includes(name) && mine !== `secret:${name}`);
  let name = `llm-${id}`;
  for (let n = 2; taken(name); n += 1) name = `llm-${id}-${n}`;
  return name;
}
