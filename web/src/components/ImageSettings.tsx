import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { ApiError, get, post, put } from '../api';
import { t, tm } from '../i18n';
import { useToast } from './Toasts';

type Connection = {
  status: {
    connected: boolean;
    owned: boolean;
    operation: string | null;
    error: any;
    url: string;
    running: number;
    pending: number;
    system: { comfyui_version?: string };
    devices: { name: string; vram_total?: number; vram_free?: number }[];
    can_start: boolean;
    can_stop: boolean;
    can_restart: boolean;
  };
  config: { url: string; python_path: string; comfy_path: string; arguments: string[] };
  gpu: { holder: string | null; label: any; state_label: any; vram_free_mb?: number; vram_total_mb?: number; waiting: any };
};
type Candidate = { comfy_path: string; python_path: string; kind: string; source: string; version?: string };

const message = (value: any) => (value && typeof value === 'object' ? tm(value) : String(value ?? ''));

// Settings → Image: image generation server connection, model folder and families, GPU wait rules.
export default function ImageSettings() {
  return (
    <div className="col" style={{ maxWidth: 820, gap: 16 }}>
      <ConnectionSection />
      <ModelsSection />
      <GpuSection />
      <ReviewSection />
      <TrainingSection />
      <p className="faint">{t('settings.tags_note')}</p>
    </div>
  );
}

function useFail() {
  const toast = useToast();
  return (err: unknown) => toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
}

function ConnectionSection() {
  const qc = useQueryClient();
  const toast = useToast();
  const fail = useFail();
  const connection = useQuery<Connection>({ queryKey: ['image-connection'], queryFn: () => get('/api/image/connection'), refetchInterval: 4000 });
  const [form, setForm] = useState<Connection['config'] | null>(null);
  const [candidates, setCandidates] = useState<Candidate[] | null>(null);
  const [finding, setFinding] = useState(false);
  const discoveryStarted = useRef(false);
  useEffect(() => {
    if (!connection.data || discoveryStarted.current) return;
    discoveryStarted.current = true;
    setFinding(true);
    get<{ candidates: Candidate[] }>('/api/image/locate')
      .then(result => setCandidates(result.candidates))
      .catch(fail).finally(() => setFinding(false));
  }, [connection.data]);

  useEffect(() => {
    if (connection.data && !form) setForm(connection.data.config);
  }, [connection.data, form]);

  if (!connection.data || !form) return null;
  const { status, gpu } = connection.data;

  async function save(config = form) {
    try {
      await put('/api/image/connection', config);
      qc.invalidateQueries({ queryKey: ['image-connection'] });
      qc.invalidateQueries({ queryKey: ['image-catalog'] });
      toast({ text: t('common.saved') });
    } catch (err) {
      fail(err);
    }
  }

  async function control(action: string) {
    try {
      await post('/api/image/connection/control', { action });
      qc.invalidateQueries({ queryKey: ['image-connection'] });
    } catch (err) {
      fail(err);
    }
  }

  return (
    <section className="col">
      <div className="section-title">{t('image_settings.connection')}</div>
      <div className="row">
        <span className={`dot-status ${status.connected ? 'ok' : 'off'}`} />
        <strong>{status.connected ? t('image_settings.connected') : t('image_settings.disconnected')}</strong>
        {status.system?.comfyui_version && <span className="faint">ComfyUI {status.system.comfyui_version}</span>}
        {status.devices?.[0] && <span className="faint">{status.devices[0].name.replace(/^cuda:\d+\s*/, '').split(' : ')[0]}</span>}
        {status.connected && <span className="faint">{t('image_settings.queue_state', { running: status.running, pending: status.pending })}</span>}
        <span className="grow" />
        {status.operation && <span className="faint">{t('image_settings.operation', { action: status.operation })}</span>}
        <button disabled={!status.can_start} onClick={() => control('start')}>
          {t('image_settings.start')}
        </button>
        <button disabled={!status.can_restart} onClick={() => control('restart')}>
          {t('image_settings.restart')}
        </button>
        <button disabled={!status.can_stop} onClick={() => control('stop')}>
          {t('image_settings.stop')}
        </button>
      </div>
      {status.error && !status.connected && <div className="warn-text">{message(status.error)}</div>}
      <p className="faint">{t('image_settings.connection_note')}</p>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('image_settings.url')}</span>
        <input className="mono" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
      </label>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('image_settings.comfy_path')}</span>
        <input className="mono" value={form.comfy_path} placeholder="C:\\…\\ComfyUI" onChange={(e) => setForm({ ...form, comfy_path: e.target.value })} />
      </label>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('image_settings.python_path')}</span>
        <input className="mono" value={form.python_path} placeholder="C:\\…\\python.exe" onChange={(e) => setForm({ ...form, python_path: e.target.value })} />
      </label>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('image_settings.arguments')}</span>
        <input
          className="mono"
          value={form.arguments.join(' ')}
          onChange={(e) => setForm({ ...form, arguments: e.target.value.split(/\s+/).filter(Boolean) })}
        />
      </label>
      <div className="row">
        <button className="primary" onClick={() => save()}>
          {t('common.save')}
        </button>
        <button
          disabled={finding}
          onClick={async () => {
            setFinding(true);
            try {
              setCandidates((await get<{ candidates: Candidate[] }>('/api/image/locate')).candidates);
            } catch (err) {
              fail(err);
            } finally {
              setFinding(false);
            }
          }}
        >
          {finding ? t('image_settings.finding') : t('image_settings.find')}
        </button>
      </div>
      {candidates && candidates.length === 0 && <div className="faint">{t('image_settings.none_found')}</div>}
      {candidates?.map((c) => (
        <div key={c.comfy_path} className="list-row">
          <span className="grow">
            <strong>{t(`image_settings.kind.${c.kind}`)}</strong> <span className="mono faint">{c.comfy_path}</span>
            {c.source === 'running' && <span className="chip" style={{ marginLeft: 6 }}>{t('image_settings.running')}</span>}
          </span>
          <button onClick={() => { const next = { ...form, comfy_path: c.comfy_path, python_path: c.python_path }; setForm(next); save(next); }}>{t('image_settings.use_save')}</button>
        </div>
      ))}
      <div className="faint">
        {t('image_settings.gpu_holder', { name: message(gpu.label) })}
        {gpu.state_label ? ` · ${message(gpu.state_label)}` : ''}
        {gpu.vram_total_mb ? ` · VRAM ${gpu.vram_free_mb?.toLocaleString()} / ${gpu.vram_total_mb.toLocaleString()} MB` : ''}
        {gpu.waiting ? ` · ${message(gpu.waiting.reason)}` : ''}
      </div>
    </section>
  );
}

type Catalog = {
  connected: boolean;
  models: string[];
  loras: string[];
  model_entries?: Record<string, { label: any }>;
  families?: { models?: Record<string, string | null>; loras?: Record<string, string | null> };
  family_labels: Record<string, any>;
};

function ModelsSection() {
  const qc = useQueryClient();
  const fail = useFail();
  const catalog = useQuery<Catalog>({ queryKey: ['image-catalog'], queryFn: () => get('/api/image/catalog') });
  const settings = useQuery<{ models_dir: string }>({ queryKey: ['image-settings', 'models'], queryFn: () => get('/api/image/settings/models') });
  const [dir, setDir] = useState<string | null>(null);
  const [showLoras, setShowLoras] = useState(false);
  const data = catalog.data;
  const folder = dir ?? settings.data?.models_dir ?? '';

  async function setFamily(kind: string, name: string, family: string) {
    try {
      await put('/api/image/models/family', { kind, name, family: family || null });
      qc.invalidateQueries({ queryKey: ['image-catalog'] });
    } catch (err) {
      fail(err);
    }
  }

  const rows = (key: 'models' | 'loras') =>
    (data?.[key] ?? []).map((name) => {
      const family = data?.families?.[key]?.[name] ?? null;
      const kind = key === 'loras' ? 'loras' : name.startsWith('checkpoint::') ? 'checkpoints' : 'diffusion_models';
      const file = name.replace(/^checkpoint::/, '');
      return (
        <tr key={name}>
          <td className="mono" style={{ wordBreak: 'break-all' }}>
            {file}
            {name.startsWith('checkpoint::') && <span className="faint"> [checkpoint]</span>}
          </td>
          <td>
            <select value={family ?? ''} onChange={(e) => setFamily(kind, file, e.target.value)}>
              <option value="">{message(data?.family_labels?.unknown)}</option>
              <option value="anima">Anima</option>
              <option value="sdxl">SDXL·IL</option>
            </select>
          </td>
        </tr>
      );
    });

  return (
    <section className="col">
      <div className="section-title">{t('image_settings.models')}</div>
      <p className="faint">{t('image_settings.models_note')}</p>
      <div className="row">
        <input className="mono grow" value={folder} placeholder={t('image_settings.models_dir_hint')} onChange={(e) => setDir(e.target.value)} />
        <button
          onClick={async () => {
            try {
              await put('/api/image/settings/models', { models_dir: folder });
              qc.invalidateQueries({ queryKey: ['image-catalog'] });
              qc.invalidateQueries({ queryKey: ['image-settings', 'models'] });
            } catch (err) {
              fail(err);
            }
          }}
        >
          {t('common.save')}
        </button>
      </div>
      {!data?.connected ? (
        <div className="faint">{t('image_settings.connect_first')}</div>
      ) : (
        <>
          <table className="plain">
            <tbody>{rows('models')}</tbody>
          </table>
          <label className="row" style={{ gap: 4 }}>
            <input type="checkbox" checked={showLoras} onChange={(e) => setShowLoras(e.target.checked)} />
            {t('image_settings.show_loras', { n: data.loras.length })}
          </label>
          {showLoras && (
            <table className="plain">
              <tbody>{rows('loras')}</tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}

type GpuSettings = { enabled: boolean; min_free_vram_mb: Record<string, number>; watch_processes: string[] };

function GpuSection() {
  const qc = useQueryClient();
  const toast = useToast();
  const fail = useFail();
  const query = useQuery<GpuSettings>({ queryKey: ['image-settings', 'gpu'], queryFn: () => get('/api/image/settings/gpu') });
  const [form, setForm] = useState<GpuSettings | null>(null);
  useEffect(() => {
    if (query.data && !form) setForm(query.data);
  }, [query.data, form]);
  if (!form) return null;
  return (
    <section className="col">
      <div className="section-title">{t('image_settings.gpu')}</div>
      <label className="row" style={{ gap: 4 }}>
        <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
        {t('image_settings.gpu_enabled')}
      </label>
      <p className="faint">{t('image_settings.gpu_note')}</p>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        {(['generation', 'tool', 'vlm', 'training'] as const).map((kind) => (
          <label key={kind} className="row" style={{ gap: 4 }}>
            <span className="muted">{t(`image_settings.gpu_kind.${kind}`)}</span>
            <input
              type="number"
              style={{ width: 90 }}
              disabled={!form.enabled}
              value={form.min_free_vram_mb[kind] ?? 0}
              onChange={(e) => setForm({ ...form, min_free_vram_mb: { ...form.min_free_vram_mb, [kind]: Number(e.target.value) } })}
            />
            <span className="faint">MB</span>
          </label>
        ))}
      </div>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('image_settings.watch_processes')}</span>
        <textarea
          rows={3}
          className="mono"
          disabled={!form.enabled}
          value={form.watch_processes.join('\n')}
          onChange={(e) => setForm({ ...form, watch_processes: e.target.value.split('\n') })}
        />
      </label>
      <div>
        <button
          className="primary"
          onClick={async () => {
            try {
              const saved = await put<GpuSettings>('/api/image/settings/gpu', { ...form, watch_processes: form.watch_processes.filter((x) => x.trim()) });
              setForm(saved);
              qc.invalidateQueries({ queryKey: ['image-connection'] });
              toast({ text: t('common.saved') });
            } catch (err) {
              fail(err);
            }
          }}
        >
          {t('common.save')}
        </button>
      </div>
    </section>
  );
}

type ReviewSettings = {
  enabled: boolean;
  max_auto_regenerations: number;
  instruction: string;
  unload_command: string[];
  default_instruction: string;
  connection: { id?: string; name?: string; model?: string; local?: boolean; error?: any };
};

// VLM auto review (21-gallery): which LLM connection looks at images is chosen in Settings → LLM (image review task).
function ReviewSection() {
  const toast = useToast();
  const fail = useFail();
  const query = useQuery<ReviewSettings>({ queryKey: ['review-settings'], queryFn: () => get('/api/image/review/settings') });
  const [form, setForm] = useState<ReviewSettings | null>(null);
  useEffect(() => {
    if (query.data && !form) setForm(query.data);
  }, [query.data, form]);
  if (!form) return null;
  const connection = form.connection;
  return (
    <section className="col">
      <div className="section-title">{t('image_settings.review')}</div>
      <p className="faint">{t('image_settings.review_note')}</p>
      <div>
        <span className="muted">{t('image_settings.review_connection')}: </span>
        {connection.error ? (
          <span className="error-text">{message(connection.error)}</span>
        ) : (
          <span>
            {connection.name} · {connection.model ?? '?'} {connection.local === false && <span className="warn-text">({t('image_settings.review_external')})</span>}
          </span>
        )}
      </div>
      <label className="row" style={{ gap: 4 }}>
        <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
        {t('image_settings.review_enabled')}
      </label>
      <label className="row" style={{ gap: 4 }}>
        <span className="muted">{t('image_settings.review_limit')}</span>
        <input type="number" min={0} max={20} style={{ width: 72 }} value={form.max_auto_regenerations} onChange={(e) => setForm({ ...form, max_auto_regenerations: Number(e.target.value) })} />
      </label>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('image_settings.review_instruction')}</span>
        <textarea rows={4} placeholder={form.default_instruction} value={form.instruction} onChange={(e) => setForm({ ...form, instruction: e.target.value })} />
      </label>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('image_settings.review_unload')}</span>
        <input className="mono" placeholder="lms unload --all" value={form.unload_command.join(' ')} onChange={(e) => setForm({ ...form, unload_command: e.target.value.split(' ').filter(Boolean) })} />
        <span className="faint">{t('image_settings.review_unload_note')}</span>
      </label>
      <div>
        <button
          className="primary"
          onClick={async () => {
            try {
              const saved = await put<ReviewSettings>('/api/image/review/settings', form);
              setForm(saved);
              toast({ text: t('common.saved') });
            } catch (err) {
              fail(err);
            }
          }}
        >
          {t('common.save')}
        </button>
      </div>
    </section>
  );
}

type Training = { trainer_dir: string; trainer_python: string; lora_dir: string; bases: Record<string, { dit: string; text_encoder: string; vae: string }> };

// LoRA training (23-lora-training): the separately installed trainer, where finished LoRAs go, and the training models.
function TrainingSection() {
  const qc = useQueryClient();
  const toast = useToast();
  const fail = useFail();
  const status = useQuery<any>({ queryKey: ['training-status'], queryFn: () => get('/api/image/training/status') });
  const [form, setForm] = useState<Training | null>(null);
  useEffect(() => {
    if (status.data && !form) setForm(status.data.settings);
  }, [status.data, form]);
  if (!form || !status.data) return null;
  const s = status.data;
  const mark = (ok: boolean) => <span className={ok ? 'ok-text' : 'faint'}>{ok ? '✓' : '—'}</span>;
  const files = (base: 'official' | 'generation') =>
    (['dit', 'text_encoder', 'vae'] as const).map((key) => (
      <label key={key} className="row" style={{ gap: 4 }}>
        <span className="muted" style={{ minWidth: 110 }}>
          {t(`image_settings.training.${key}`)}
        </span>
        <input
          className="mono grow"
          value={form.bases?.[base]?.[key] ?? ''}
          onChange={(e) => setForm({ ...form, bases: { ...form.bases, [base]: { ...(form.bases?.[base] ?? { dit: '', text_encoder: '', vae: '' }), [key]: e.target.value } } })}
        />
        {mark(!!s.files[`${base}.${key}`])}
      </label>
    ));
  return (
    <section className="col">
      <div className="section-title">{t('image_settings.training')}</div>
      <p className="faint">{t('image_settings.training_note')}</p>
      <pre className="mono small">uv run python tools/install_trainer.py --yes</pre>
      <label className="row" style={{ gap: 4 }}>
        <span className="muted" style={{ minWidth: 110 }}>
          {t('image_settings.training.trainer_dir')}
        </span>
        <input className="mono grow" placeholder="vendor/anima_lora" value={form.trainer_dir} onChange={(e) => setForm({ ...form, trainer_dir: e.target.value })} />
        {mark(s.trainer_found)}
        {s.trainer_found && !s.patched && <span className="warn-text small">{t('image_settings.training.not_patched')}</span>}
      </label>
      <label className="row" style={{ gap: 4 }}>
        <span className="muted" style={{ minWidth: 110 }}>
          {t('image_settings.training.python')}
        </span>
        <input className="mono grow" value={form.trainer_python} onChange={(e) => setForm({ ...form, trainer_python: e.target.value })} />
        {mark(s.python_found)}
      </label>
      <label className="row" style={{ gap: 4 }}>
        <span className="muted" style={{ minWidth: 110 }}>
          {t('image_settings.training.lora_dir')}
        </span>
        <input className="mono grow" value={form.lora_dir} onChange={(e) => setForm({ ...form, lora_dir: e.target.value })} />
        {mark(s.lora_dir_found)}
      </label>
      <div className="muted">{t('image_settings.training.official')}</div>
      {files('official')}
      <div className="muted">{t('image_settings.training.generation')}</div>
      {files('generation')}
      <div>
        <button
          className="primary"
          onClick={async () => {
            try {
              const saved = await put<Training>('/api/image/settings/training', form);
              setForm(saved);
              qc.invalidateQueries({ queryKey: ['training-status'] });
              toast({ text: t('common.saved') });
            } catch (err) {
              fail(err);
            }
          }}
        >
          {t('common.save')}
        </button>
      </div>
    </section>
  );
}
