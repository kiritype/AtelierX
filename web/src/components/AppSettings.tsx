import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';
import { ApiError, del, get, patch, post, put } from '../api';
import { setLanguage, t, tm } from '../i18n';
import DeploySettings from './DeploySettings';
import ImageSettings from './ImageSettings';
import InstallSettings from './InstallSettings';
import LlmSettings from './LlmSettings';
import GuidelineSettings from './GuidelineSettings';
import { AboutContent, useHelp } from './Help';
import type { MenuAction } from './MenuBar';
import { useToast } from './Toasts';
import { useUnsaved } from './Unsaved';
import { SettingsPackages } from './Packages';

type Section = 'general' | 'presets' | 'llm' | 'vault' | 'guidelines' | 'image' | 'deploy' | 'install' | 'packages' | 'about';
const SECTIONS: Section[] = ['general', 'presets', 'llm', 'vault', 'guidelines', 'image', 'deploy', 'install', 'packages', 'about'];

export default function AppSettings({ request }: { request?: { section: string; at: number } }) {
  const [section, setSection] = useState<Section>('general');
  // A section stays mounted once opened, so moving to another one and back keeps what was typed but not yet saved.
  const [visited, setVisited] = useState<Set<Section>>(() => new Set(['general']));
  const selectSection = (key: Section) => {
    setSection(key);
    setVisited((all) => (all.has(key) ? all : new Set([...all, key])));
  };
  // Another screen asked for a section (image tools -> Install); `at` repeats the request after the user moved away.
  useEffect(() => {
    if (request && (SECTIONS as string[]).includes(request.section)) selectSection(request.section as Section);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request?.section, request?.at]);
  const panes: Record<Section, ReactNode> = {
    general: <General />,
    presets: <Presets />,
    llm: <LlmSettings />,
    vault: <VaultSection />,
    guidelines: <GuidelineSettings />,
    image: <ImageSettings />,
    deploy: <DeploySettings />,
    install: <InstallSettings />,
    packages: <SettingsPackages />,
    about: <About />,
  };
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '180px 1fr', height: '100%' }}>
      <div style={{ borderRight: '1px solid var(--border)', paddingTop: 8 }}>
        {SECTIONS.map((key) => (
          <div key={key} className={`tree-row${section === key ? ' sel' : ''}`} onClick={() => selectSection(key)}>
            {t(`settings.${key}`)}
          </div>
        ))}
      </div>
      <div className="pad" style={{ overflow: 'auto' }}>
        {SECTIONS.filter((key) => visited.has(key)).map((key) => (
          <div key={key} hidden={section !== key}>
            {panes[key]}
          </div>
        ))}
      </div>
    </div>
  );
}

function useFail() {
  const toast = useToast();
  return (err: unknown) => toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
}

function General() {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => get('/api/settings') });
  const presets = useQuery({ queryKey: ['platforms'], queryFn: () => get('/api/platforms') });
  if (!settings.data) return null;
  const s = settings.data;
  const update = async (changes: Record<string, any>) => {
    qc.setQueryData(['settings'], await patch('/api/settings', changes));
  };
  return (
    <div className="col" style={{ maxWidth: 520 }}>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('settings.language')}</span>
        <select
          value={s.language}
          onChange={(e) => {
            setLanguage(e.target.value);
            update({ language: e.target.value });
          }}
        >
          <option value="ko">한국어</option>
          <option value="en">English</option>
        </select>
      </label>
      <label className="row">
        <input type="checkbox" checked={s.autosave.enabled} onChange={(e) => update({ autosave: { enabled: e.target.checked } })} />
        {t('settings.autosave')}
      </label>
      <label className="row" title={t('settings.update_check_note')}>
        <input type="checkbox" checked={!!s.update_check_on_start} onChange={(e) => update({ update_check_on_start: e.target.checked })} />
        {t('settings.update_check_on_start')}
      </label>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('settings.default_preset')}</span>
        <select value={s.default_platform_preset ?? ''} onChange={(e) => update({ default_platform_preset: e.target.value || null })}>
          <option value="">{t('settings.none')}</option>
          {(presets.data ?? [])
            .filter((p: any) => p.id !== 'generic')
            .map((p: any) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.id})
              </option>
            ))}
        </select>
      </label>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('settings.snapshot_interval')}</span>
        <input type="number" value={s.snapshot_interval_minutes} onChange={(e) => update({ snapshot_interval_minutes: Number(e.target.value) })} />
      </label>
    </div>
  );
}

function Presets() {
  const qc = useQueryClient();
  const fail = useFail();
  const toast = useToast();
  const list = useQuery({ queryKey: ['platforms'], queryFn: () => get('/api/platforms') });
  const [selected, setSelected] = useState('generic');
  const preset = useQuery({ queryKey: ['platform', selected], queryFn: () => get(`/api/platforms/${selected}`) });
  const [draft, setDraft] = useState<any>(null);
  const readonly = list.data?.find((p: any) => p.id === selected)?.readonly;
  useUnsaved('presets', !!draft);
  const doc = draft ?? preset.data;
  const changeLimit = (key: 'main' | 'lorebook_entry', value: string) => {
    setDraft({ ...doc, count: 'utf8_bytes', limits: { ...doc.limits,
      [key]: { ...doc.limits?.[key], max: value === '' ? null : Number(value) } } });
  };

  return (
    <div className="col">
      <div className="row">
        <select value={selected} onChange={(e) => {
          if (draft && !confirm(t('settings.platform_discard_confirm'))) return;
          setSelected(e.target.value);
          setDraft(null);
        }}>
          {(list.data ?? []).map((p: any) => (
            <option key={p.id} value={p.id}>
              {p.name} ({p.id}){p.readonly ? ` · ${t('settings.readonly')}` : ''}
            </option>
          ))}
        </select>
        <button
          onClick={async () => {
            if (draft && !confirm(t('settings.platform_discard_confirm'))) return;
            const id = prompt(t('settings.preset_id_prompt'));
            if (!id) return;
            const name = prompt(t('settings.platform_name_prompt'), id);
            if (!name) return;
            try {
              const created = await post('/api/platforms', { id, name });
              qc.invalidateQueries({ queryKey: ['platforms'] });
              qc.setQueryData(['platform', id], created);
              setSelected(id);
              setDraft(null);
            } catch (err) {
              fail(err);
            }
          }}
        >
          {t('settings.preset_new')}
        </button>
      </div>
      <p className="faint">{t('settings.platform_independent_note')}</p>
      {doc && (
        <div className="col" style={{ maxWidth: 520 }}>
          <label className="col"><span className="muted">{t('settings.platform_name')}</span>
            <input disabled={readonly} value={doc.name ?? ''} onChange={(e) => setDraft({ ...doc, name: e.target.value })} />
          </label>
          <label className="col"><span className="muted">{t('settings.platform_main_max')}</span>
            <input type="number" min="0" disabled={readonly} value={doc.limits?.main?.max ?? ''} onChange={(e) => changeLimit('main', e.target.value)} />
          </label>
          <label className="col"><span className="muted">{t('settings.platform_lorebook_max')}</span>
            <input type="number" min="0" disabled={readonly} value={doc.limits?.lorebook_entry?.max ?? ''} onChange={(e) => changeLimit('lorebook_entry', e.target.value)} />
          </label>
          <span className="faint">{t('settings.platform_limits_note')}</span>
          {/* How this platform passes attribute values of component calls in a reply (07-jsx: 응답 속 컴포넌트 표기). */}
          <label className="col"><span className="muted">{t('settings.platform_attribute_format')}</span>
            <select
              disabled={readonly}
              value={doc.jsx?.response?.attribute_format ?? 'json_lenient'}
              onChange={(e) => setDraft({ ...doc, jsx: { ...doc.jsx, response: { syntax: 'element', ...doc.jsx?.response, attribute_format: e.target.value } } })}
            >
              {(['text', 'json_lenient', 'json'] as const).map((format) => (
                <option key={format} value={format}>{t(`jsx.format.${format}`)}</option>
              ))}
            </select>
          </label>
          <span className="faint">{t('settings.platform_attribute_format_note')}</span>
        </div>
      )}
      {!readonly && doc && (
        <div className="row">
          <button
            className="primary"
            onClick={async () => {
              try {
                const saved = await put(`/api/platforms/${selected}`, { ...doc, count: 'utf8_bytes' });
                qc.setQueryData(['platform', selected], saved);
                setDraft(null);
                qc.invalidateQueries({ queryKey: ['platform', selected] });
                qc.invalidateQueries({ queryKey: ['platforms'] });
                qc.invalidateQueries({ queryKey: ['work'] });
                toast({ text: t('common.saved') });
              } catch (err) {
                fail(err);
              }
            }}
          >
            {t('common.save')}
          </button>
          <button className="danger" onClick={async () => {
            if (!confirm(t('settings.platform_delete_confirm'))) return;
            try {
              await del(`/api/platforms/${selected}`);
              qc.removeQueries({ queryKey: ['platform', selected] });
              qc.invalidateQueries({ queryKey: ['platforms'] });
              setSelected('generic'); setDraft(null);
            } catch (err) { fail(err); }
          }}>{t('common.delete')}</button>
        </div>
      )}
    </div>
  );
}

function VaultSection() {
  const qc = useQueryClient();
  const fail = useFail();
  const toast = useToast();
  const vault = useQuery({ queryKey: ['vault'], queryFn: () => get('/api/vault') });
  const providers = useQuery<{ providers: Record<string, { name: string; key?: string | null }> }>({ queryKey: ['providers'], queryFn: () => get('/api/providers') });
  const usedBy = (name: string) =>
    Object.values(providers.data?.providers ?? {}).filter((p) => p.key === `secret:${name}`).map((p) => p.name);
  const [form, setForm] = useState({ name: '', kind: 'llm_api_key', value: '', note: '' });
  const [pw, setPw] = useState({ old: '', new: '' });
  useUnsaved('vault', !!(form.name || form.value || form.note || pw.old || pw.new));
  return (
    <div className="col" style={{ maxWidth: 640 }}>
      <p className="faint">{t('settings.vault_note')}</p>
      {(vault.data ?? []).map((v: any) => (
        <div key={v.name} className="list-row">
          <span className="grow">
            <strong>{v.name}</strong> <span className="faint">{v.kind}</span> <code>{v.masked}</code>
            <div className="faint small">
              {usedBy(v.name).length ? t('settings.vault_used_by', { names: usedBy(v.name).join(', ') }) : t('settings.vault_unused')}
            </div>
          </span>
          <button
            className="danger"
            onClick={async () => {
              const users = usedBy(v.name);
              if (!confirm(users.length ? t('settings.vault_delete_used', { names: users.join(', ') }) : t('settings.vault_delete_confirm'))) return;
              await del(`/api/vault/${encodeURIComponent(v.name)}`);
              qc.invalidateQueries({ queryKey: ['vault'] });
            }}
          >
            {t('common.delete')}
          </button>
        </div>
      ))}
      <div className="row">
        <input placeholder={t('settings.vault_name')} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
          {['llm_api_key', 'service_token', 'server_auth', 'other'].map((k) => (
            <option key={k}>{k}</option>
          ))}
        </select>
        <input type="password" className="grow" placeholder={t('settings.vault_value')} value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} />
        <button
          onClick={async () => {
            try {
              await post('/api/vault', form);
              setForm({ name: '', kind: 'llm_api_key', value: '', note: '' });
              qc.invalidateQueries({ queryKey: ['vault'] });
            } catch (err) {
              fail(err);
            }
          }}
        >
          {t('common.add')}
        </button>
      </div>
      <div className="section-title">{t('settings.change_password')}</div>
      <div className="row">
        <input type="password" placeholder={t('settings.old_password')} value={pw.old} onChange={(e) => setPw({ ...pw, old: e.target.value })} />
        <input type="password" placeholder={t('settings.new_password')} value={pw.new} onChange={(e) => setPw({ ...pw, new: e.target.value })} />
        <button
          onClick={async () => {
            try {
              await post('/api/vault/password', pw);
              setPw({ old: '', new: '' });
              toast({ text: t('settings.password_changed') });
            } catch (err) {
              fail(err);
            }
          }}
        >
          {t('common.save')}
        </button>
      </div>
    </div>
  );
}

function About() {
  const help = useHelp();
  const about = useQuery({ queryKey: ['about'], queryFn: () => get('/api/about'), staleTime: Infinity });
  return (
    <div className="col" style={{ maxWidth: 560 }}>
      {about.data ? <AboutContent about={about.data} /> : <strong>AtelierX {__APP_VERSION__}</strong>}
      <span className="faint">{t('settings.about_stage')}</span>
      <div className="row wrap">
        {help.entries.filter((e): e is MenuAction => !!e && 'run' in e).map((e) => (
          <button key={e.label} onClick={e.run}>{e.label}</button>
        ))}
      </div>
      {help.element}
    </div>
  );
}
