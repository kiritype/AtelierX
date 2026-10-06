import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { ApiError, get, post, put } from '../api';
import { t, tm } from '../i18n';
import { KeyField } from './LlmSettings';
import { useToast } from './Toasts';
import { useUnsaved } from './Unsaved';

type KeyName = 'access_key_id' | 'secret_access_key';
type Target = {
  name: string;
  kind: 'r2';
  account_id: string;
  bucket: string;
  access_key_id: string | null;
  secret_access_key: string | null;
  public_url: string;
  path_format: string;
};
type Listed = Target & { id: string; ready: boolean };
type Doc = { targets: Listed[]; placeholders: string[]; default_format: string };
type Vault = { name: string; kind: string; masked: string }[];

const FIELDS: (keyof Target)[] = ['name', 'account_id', 'bucket', 'public_url', 'path_format'];
const formOf = (doc: Doc): Record<string, Target> =>
  Object.fromEntries(doc.targets.map(({ id, ready: _ready, ...target }) => [id, target]));

// The vault entry a target's key goes into: `deploy-<id>-id` / `-secret`, numbered when that name holds another key.
function keyName(id: string, field: KeyName, current: string | null, stored: string[]) {
  const base = `deploy-${id}-${field === 'access_key_id' ? 'id' : 'secret'}`;
  let name = base;
  for (let n = 2; stored.includes(name) && current !== `secret:${name}`; n += 1) name = `${base}-${n}`;
  return name;
}

// Settings → Deployment targets (decision 0023): where adopted images are uploaded. Keys stay in the vault.
export default function DeploySettings() {
  const qc = useQueryClient();
  const toast = useToast();
  const query = useQuery<Doc>({ queryKey: ['deploy-targets'], queryFn: () => get('/api/image/deploy/targets') });
  const vault = useQuery<Vault>({ queryKey: ['vault'], queryFn: () => get('/api/vault') });
  const [form, setForm] = useState<Record<string, Target> | null>(null);
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [changing, setChanging] = useState<Record<string, boolean>>({});
  const [checking, setChecking] = useState('');
  useEffect(() => {
    if (query.data && !form) setForm(formOf(query.data));
  }, [query.data, form]);
  const dirty = !!form && !!query.data && (JSON.stringify(form) !== JSON.stringify(formOf(query.data)) || Object.values(keys).some((k) => k.trim()));
  useUnsaved('deploy-targets', dirty);
  if (!form || !query.data) return null;
  const fail = (err: unknown) => toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });

  const set = (id: string, change: Partial<Target>) => setForm({ ...form, [id]: { ...form[id], ...change } });
  const add = () => {
    let n = 1;
    while (form[`r2-${n}`]) n += 1;
    const id = `r2-${n}`;
    setForm({
      ...form,
      [id]: { name: '', kind: 'r2', account_id: '', bucket: '', access_key_id: null, secret_access_key: null, public_url: '', path_format: query.data!.default_format },
    });
  };
  const remove = (id: string) => {
    if (!confirm(t('deploy.remove_confirm', { name: form[id].name || id }))) return;
    const next = { ...form };
    delete next[id];
    setForm(next);
  };

  async function save() {
    try {
      const next = structuredClone(form!);
      const stored = (vault.data ?? []).map((v) => v.name);
      for (const [slot, value] of Object.entries(keys)) {
        if (!value.trim()) continue;
        const [id, field] = slot.split('|') as [string, KeyName];
        if (!next[id]) continue;
        const name = keyName(id, field, next[id][field], stored);
        await post('/api/vault', { name, kind: 'api_key', value: value.trim(), note: `${next[id].name || id} (${t(`deploy.${field}`)})` });
        stored.push(name);
        next[id][field] = `secret:${name}`;
      }
      const saved = await put<Doc>('/api/image/deploy/targets', { targets: next });
      qc.setQueryData(['deploy-targets'], saved);
      qc.invalidateQueries({ queryKey: ['vault'] });
      setForm(formOf(saved));
      setKeys({});
      setChanging({});
      toast({ text: t('common.saved') });
    } catch (err) {
      fail(err);
    }
  }

  async function check(id: string) {
    setChecking(id);
    try {
      await post(`/api/image/deploy/targets/${id}/check`);
      toast({ text: t('deploy.check_ok') });
    } catch (err) {
      fail(err);
    } finally {
      setChecking('');
    }
  }

  const listed = Object.fromEntries(query.data.targets.map((target) => [target.id, target]));
  return (
    <section className="col" style={{ maxWidth: 860, gap: 12 }}>
      <div className="section-title">{t('settings.deploy')}</div>
      <p className="faint small">{t('deploy.about')}</p>
      <div className="notice col small">
        <strong>{t('deploy.public_title')}</strong>
        <span>{t('deploy.public_note')}</span>
      </div>
      {Object.entries(form).map(([id, target]) => {
        const saved = listed[id];
        const r2dev = /\.r2\.dev(\/|$)/i.test(target.public_url);
        return (
          <div key={id} className="card col" style={{ gap: 6, width: 'auto', padding: 16 }}>
            <div className="row">
              <strong className="grow">
                {target.name || id} <span className="faint mono small">{id}</span>
              </strong>
              <span className={`chip${saved?.ready ? ' ok' : ''}`}>{saved ? (saved.ready ? t('deploy.ready') : t('deploy.no_keys')) : t('deploy.unsaved')}</span>
              <button disabled={!saved?.ready || dirty || checking === id} onClick={() => check(id)} title={dirty ? t('deploy.save_first') : undefined}>
                {checking === id ? t('deploy.checking') : t('deploy.check')}
              </button>
              <button className="danger" onClick={() => remove(id)}>
                {t('common.delete')}
              </button>
            </div>
            {FIELDS.map((field) => (
              <label key={field}>
                {t(`deploy.${field}`)}
                <input
                  className={field === 'path_format' || field === 'account_id' ? 'mono' : undefined}
                  value={target[field] as string}
                  placeholder={field === 'public_url' ? 'https://img.example.com' : field === 'path_format' ? query.data!.default_format : ''}
                  onChange={(e) => set(id, { [field]: e.target.value })}
                />
              </label>
            ))}
            <span className="faint small">{t('deploy.path_format_hint')}</span>
            {r2dev && <span className="warn-text small">{t('deploy.r2dev')}</span>}
            {(['access_key_id', 'secret_access_key'] as KeyName[]).map((field) => (
              <div key={field} className="row" style={{ flexWrap: 'wrap' }}>
                <span className="muted" style={{ width: 130 }}>{t(`deploy.${field}`)}</span>
                <KeyField
                  provider={{ key: target[field] } as never}
                  vault={vault.data ?? []}
                  typed={keys[`${id}|${field}`] ?? ''}
                  changing={!!changing[`${id}|${field}`]}
                  onType={(value) => setKeys({ ...keys, [`${id}|${field}`]: value })}
                  onChange={(on) => setChanging({ ...changing, [`${id}|${field}`]: on })}
                  onPick={(name) => set(id, { [field]: name ? `secret:${name}` : null })}
                />
              </div>
            ))}
            <span className="faint small">{t('deploy.key_hint')}</span>
          </div>
        );
      })}
      {Object.keys(form).length === 0 && <div className="empty">{t('deploy.empty')}</div>}
      <div className="row">
        <button onClick={add}>{t('deploy.add')}</button>
        <button className="primary" disabled={!dirty} onClick={save}>
          {t('common.save')}
        </button>
      </div>
    </section>
  );
}
