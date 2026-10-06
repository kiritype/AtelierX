import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { ApiError, get, post, put } from '../api';
import { t, tm } from '../i18n';
import { KeyField } from './LlmSettings';
import { useToast } from './Toasts';
import { useReportDirty } from './settingsDirty';
import { pixaiVersionId, type PixAILora } from '../lib/pixai';

export type ImageService = { id: string; name: string; key: string | null; interval: number; supported: boolean; connected: boolean; loras?: PixAILora[] };
export type ImageServices = { max_images_per_run: number; services: ImageService[] };
type Form = { max_images_per_run: number; services: Record<string, { key: string | null; interval: number; loras?: PixAILora[] }> };

const formOf = (doc: ImageServices): Form => ({
  max_images_per_run: doc.max_images_per_run,
  services: Object.fromEntries(doc.services.map((s) => [s.id, { key: s.key, interval: s.interval, ...(s.loras ? { loras: s.loras } : {}) }])),
});

// The vault entry a service's new key goes into: `image-<id>`, or `image-<id>-2` … when that name holds another key.
export function imageKeyName(id: string, current: string | null, stored: string[]) {
  let name = `image-${id}`;
  for (let n = 2; stored.includes(name) && current !== `secret:${name}`; n += 1) name = `image-${id}-${n}`;
  return name;
}

// Settings → Image → Image services on the internet (#41): keys (kept in the vault), the wait between requests and the
// most images one "Add to queue" may ask for.
export default function ImageServiceSettings() {
  const qc = useQueryClient();
  const toast = useToast();
  const query = useQuery<ImageServices>({ queryKey: ['image-services'], queryFn: () => get('/api/image/services') });
  const vault = useQuery<{ name: string; kind: string; masked: string }[]>({ queryKey: ['vault'], queryFn: () => get('/api/vault') });
  const [form, setForm] = useState<Form | null>(null);
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [changing, setChanging] = useState<Record<string, boolean>>({});
  useEffect(() => {
    if (query.data && !form) setForm(formOf(query.data));
  }, [query.data, form]);
  const dirty = !!form && !!query.data && (JSON.stringify(form) !== JSON.stringify(formOf(query.data)) || Object.values(keys).some((k) => k.trim()));
  useReportDirty('image-services', dirty);
  if (!form || !query.data) return null;

  const setService = (id: string, change: Partial<Form['services'][string]>) =>
    setForm({ ...form, services: { ...form.services, [id]: { ...(form.services[id] ?? { key: null, interval: 3 }), ...change } } });

  async function save() {
    try {
      let next = form!;
      const stored = (vault.data ?? []).map((v) => v.name);
      for (const [id, value] of Object.entries(keys)) {
        if (!value.trim()) continue;
        const name = imageKeyName(id, next.services[id]?.key ?? null, stored);
        await post('/api/vault', { name, kind: 'api_key', value: value.trim(), note: query.data!.services.find((s) => s.id === id)?.name ?? id });
        next = { ...next, services: { ...next.services, [id]: { ...(next.services[id] ?? { interval: 3 }), key: `secret:${name}` } } };
      }
      const saved = await put<ImageServices>('/api/image/services', next);
      qc.setQueryData(['image-services'], saved);
      qc.invalidateQueries({ queryKey: ['vault'] });
      setForm(formOf(saved));
      setKeys({});
      setChanging({});
      toast({ text: t('common.saved') });
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    }
  }

  return (
    <section className="col">
      <div className="section-title">{t('image_services.title')}</div>
      <p className="faint small">{t('image_services.about')}</p>
      <label className="row">
        <span className="muted">{t('image_services.limit')}</span>
        <input
          type="number"
          min={0}
          style={{ width: 96 }}
          value={form.max_images_per_run}
          onChange={(e) => setForm({ ...form, max_images_per_run: Math.max(0, Math.floor(Number(e.target.value) || 0)) })}
        />
        <span className="faint small">{t('image_services.limit_hint')}</span>
      </label>
      {query.data.services.map((service) => {
        const entry = form.services[service.id] ?? { key: null, interval: 3 };
        return (
          <div key={service.id} className="card col" style={{ gap: 6 }}>
            <div className="row">
              <strong className="grow">{service.name}</strong>
              <span className={`chip${service.connected ? ' ok' : ''}`}>
                {!service.supported ? t('image_services.not_supported') : service.connected ? t('image_services.connected') : t('image_services.no_key')}
              </span>
            </div>
            <div className="row" style={{ flexWrap: 'wrap' }}>
              <span className="muted">{t('image_services.key')}</span>
              <KeyField
                provider={{ key: entry.key } as never}
                vault={vault.data ?? []}
                typed={keys[service.id] ?? ''}
                changing={!!changing[service.id]}
                onType={(value) => setKeys({ ...keys, [service.id]: value })}
                onChange={(on) => setChanging({ ...changing, [service.id]: on })}
                onPick={(name) => setService(service.id, { key: name ? `secret:${name}` : null })}
              />
            </div>
            <div className="row">
              <span className="muted">{t('image_services.interval')}</span>
              <input
                type="number"
                min={0}
                step={0.5}
                style={{ width: 80 }}
                value={entry.interval}
                onChange={(e) => setService(service.id, { interval: Math.max(0, Number(e.target.value) || 0) })}
              />
              <span className="faint small">{t('image_services.interval_hint')}</span>
            </div>
            {entry.loras && <LoraList loras={entry.loras} onChange={(loras) => setService(service.id, { loras })} />}
          </div>
        );
      })}
      <div className="row">
        <button className="primary" disabled={!dirty} onClick={save}>
          {t('common.save')}
        </button>
      </div>
    </section>
  );
}

// PixAI LoRAs (#43): PixAI's API cannot list them, so each is added from its Model Market address.
function LoraList({ loras, onChange }: { loras: PixAILora[]; onChange: (loras: PixAILora[]) => void }) {
  const [address, setAddress] = useState('');
  const [name, setName] = useState('');
  const id = pixaiVersionId(address);
  const add = () => {
    if (!id || loras.some((l) => l.id === id)) return;
    onChange([...loras, { id, name: name.trim() || id, weight: 1, trigger_words: '' }]);
    setAddress('');
    setName('');
  };
  const edit = (n: number, change: Partial<PixAILora>) => onChange(loras.map((l, i) => (i === n ? { ...l, ...change } : l)));
  return (
    <div className="col" style={{ gap: 4 }}>
      <span className="muted">{t('pixai.lora_list')}</span>
      {loras.map((lora, n) => (
        <div key={lora.id} className="row" style={{ flexWrap: 'wrap' }}>
          <input style={{ width: 140 }} value={lora.name} aria-label={t('pixai.lora_name')} onChange={(e) => edit(n, { name: e.target.value })} />
          <code className="small faint">{lora.id}</code>
          <input
            type="number"
            min={0}
            max={1}
            step={0.05}
            style={{ width: 64 }}
            aria-label={t('pixai.lora_weight')}
            value={lora.weight}
            onChange={(e) => edit(n, { weight: Math.min(1, Math.max(0, Number(e.target.value) || 0)) })}
          />
          <input className="grow" placeholder={t('pixai.trigger_words')} value={lora.trigger_words} onChange={(e) => edit(n, { trigger_words: e.target.value })} />
          <button className="ghost" title={t('common.delete')} onClick={() => onChange(loras.filter((_, i) => i !== n))}>
            ×
          </button>
        </div>
      ))}
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <input className="grow" style={{ minWidth: 240 }} placeholder={t('pixai.lora_address')} value={address} onChange={(e) => setAddress(e.target.value)} />
        <input style={{ width: 140 }} placeholder={t('pixai.lora_name')} value={name} onChange={(e) => setName(e.target.value)} />
        <button disabled={!id} onClick={add}>
          {t('pixai.lora_add')}
        </button>
      </div>
      {address.trim() && !id && <span className="warn-text small">{t('pixai.lora_address_bad')}</span>}
    </div>
  );
}
