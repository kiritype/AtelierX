import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { ApiError, get, post } from '../api';
import { getLanguage, t, tm } from '../i18n';
import { useToast } from './Toasts';
import { unfinished } from '../lib/lifecycle';

type Item = { id: string; file: string; folder: string; size?: number; manual?: string; installed: string | null; target: string | null };
type Group = { id: string; name: Record<string, string>; about: Record<string, string>; license: { name: string; url: string }; items: Item[] };
type Status = {
  run: { section: string; status: string; log: string[]; error?: any; started_at: string } | null;
  tools: {
    uv: string | null;
    git: string | null;
    bin: string;
    downloads: Record<'uv' | 'git', { version: string; size: number }>;
  };
  nodes: null | {
    comfy: string;
    python: string | null;
    steps: { id: string; action: string; node: { folder: string; version: string; license: string } }[];
    pack: { folder: string; action: string; license: string };
    broken_links: string[];
    legacy_packs: string[];
  };
  models: { connected: boolean; groups: Group[] };
  trainer: {
    folder: string;
    trainer_found: boolean;
    venv: boolean;
    patched: boolean;
    python_found: boolean;
    lora_dir_found: boolean;
    bases: { id: string }[];
    version: { repo: string; commit: string; license: string };
  };
};

const msg = (value: any) => (value && typeof value === 'object' ? tm(value) : String(value ?? ''));
const gb = (bytes: number) => (bytes >= 2 ** 30 ? `${(bytes / 2 ** 30).toFixed(1)}GB` : `${Math.max(1, Math.round(bytes / 2 ** 20))}MB`);
const readiness = {
  ko: {
    note: '글 작성·편집은 외부 도구 없이 쓸 수 있습니다. 이미지 생성과 LoRA 학습은 선택 기능이며, 이미지 생성에는 ComfyUI가 필요합니다. 필요한 영역만 설치하세요.',
    nodesNoComfy: 'ComfyUI를 찾은 뒤 설치할 수 있습니다.',
    nodesReview: '충돌이나 다른 판을 확인하세요.',
  },
  en: {
    note: 'Writing and editing work without external tools. Image generation and LoRA training are optional; image generation needs ComfyUI. Install only the sections you need.',
    nodesNoComfy: 'Find ComfyUI before installing nodes.',
    nodesReview: 'Review node conflicts or other versions.',
  },
};

type ToolName = 'uv' | 'git';
const TOOL_LABEL: Record<ToolName, string> = { uv: 'uv', git: 'Git' };

// A helper tool's state: the PC's own copy, the app's portable copy, or missing (and what would be downloaded).
function toolState(tools: Status['tools'], name: ToolName) {
  const path = tools[name];
  if (!path) {
    const d = tools.downloads[name];
    return t('install.tool_missing', { name: TOOL_LABEL[name], version: d.version, mb: Math.round(d.size / 2 ** 20) });
  }
  const own = path.toLowerCase().startsWith(tools.bin.toLowerCase());
  return t(own ? 'install.tool_app' : 'install.tool_system', { name: TOOL_LABEL[name] });
}

// Before an install that needs missing tools: they come along with it.
function ToolsComing({ tools, need }: { tools: Status['tools']; need: ToolName[] }) {
  const missing = need.filter((name) => !tools[name]);
  if (!missing.length) return null;
  const list = missing
    .map((name) => `${name === 'git' ? 'MinGit' : 'uv'} ${tools.downloads[name].version} (${Math.round(tools.downloads[name].size / 2 ** 20)}MB)`)
    .join(', ');
  return <span className="faint small">{t('install.tools_coming', { list })}</span>;
}

function Mark({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={ok ? 'ok-text' : 'faint'}>
      {ok ? '✓' : '—'} {label}
    </span>
  );
}

// Settings → Install (decision 0019): what the image features need besides the app, one section each. Nothing is
// installed until its button is pressed; progress shows in the log below the sections.
export default function InstallSettings() {
  const qc = useQueryClient();
  const toast = useToast();
  const status = useQuery<Status>({
    queryKey: ['installs'],
    queryFn: () => get('/api/image/installs'),
    refetchInterval: (q) => (unfinished((q.state.data as Status | undefined)?.run?.status) ? 1200 : 15000),
  });
  const s = status.data;
  const running = unfinished(s?.run?.status);
  const logRef = useRef<HTMLPreElement>(null);
  const lastStatus = useRef<string | undefined>(undefined);

  useEffect(() => {
    logRef.current?.scrollTo(0, logRef.current.scrollHeight);
    // When a run ends, what it installed changes other screens' lists too.
    if (unfinished(lastStatus.current) && !unfinished(s?.run?.status)) {
      for (const key of ['training-status', 'image-catalog', 'tool-post', 'tool-tagger', 'image-connection']) qc.invalidateQueries({ queryKey: [key] });
    }
    lastStatus.current = s?.run?.status;
  }, [s, qc]);

  const act = async (action: string, body?: unknown) => {
    try {
      await post(`/api/image/installs/${action}`, body ?? {});
      qc.invalidateQueries({ queryKey: ['installs'] });
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    }
  };
  if (!s) return <div className="faint">{t('install.checking')}</div>;
  const lang = getLanguage();
  const copy = readiness[lang === 'ko' ? 'ko' : 'en'];
  const nodesTodo = s.nodes ? s.nodes.steps.filter((x) => ['install', 'repair'].includes(x.action)).length + (['install', 'update'].includes(s.nodes.pack.action) ? 1 : 0) : 0;
  const nodesNeedReview = !!s.nodes && (
    s.nodes.steps.some((x) => ['blocked', 'differs'].includes(x.action))
    || ['blocked', 'missing_source'].includes(s.nodes.pack.action)
    || s.nodes.broken_links.length > 0
  );
  const tr = s.trainer;

  return (
    <div className="col" style={{ maxWidth: 860, gap: 16 }}>
      <p className="faint">{t('install.about')}</p>
      <p className="faint small">{copy.note}</p>

      <section className="col install-section">
        <div className="row">
          <div className="section-title grow">{t('install.tools')}</div>
          <button disabled={running || (!!s.tools.uv && !!s.tools.git)} onClick={() => act('tools')}>
            {t('install.get_missing')}
          </button>
        </div>
        <p className="faint small">{t('install.tools_about')}</p>
        <Mark ok={!!s.tools.uv} label={toolState(s.tools, 'uv')} />
        <Mark ok={!!s.tools.git} label={toolState(s.tools, 'git')} />
        <details><summary>{lang === 'ko' ? '도구 경로' : 'Tool paths'}</summary><div className="mono small">uv: {s.tools.uv ?? '—'}<br />Git: {s.tools.git ?? '—'}</div></details>
      </section>

      <section className="col install-section">
        <div className="row">
          <div className="section-title grow">{t('install.nodes')}</div>
          <button disabled={running || !s.nodes || nodesTodo === 0} onClick={() => act('nodes')}>
            {nodesTodo
              ? t('install.install_n', { n: nodesTodo })
              : !s.nodes
                ? copy.nodesNoComfy
                : nodesNeedReview
                  ? copy.nodesReview
                  : t('install.up_to_date')}
          </button>
          <button disabled={running} onClick={() => confirm(t('install.restart_confirm')) && act('restart-comfy')}>
            {t('install.restart_comfy')}
          </button>
        </div>
        <p className="faint small">{t('install.nodes_about')}</p>
        <ToolsComing tools={s.tools} need={['git']} />
        {!s.nodes ? (
          <div className="warn-text small">{t('install.no_comfy')}</div>
        ) : (
          <>
            <span className="faint small mono">{s.nodes.comfy}</span>
            {s.nodes.steps.map((step) => (
              <span key={step.id} className="small">
                <Mark ok={step.action === 'ok'} label={`${step.node.folder} ${step.node.version} (${step.node.license}) · ${t(`install.action.${step.action}`)}`} />
              </span>
            ))}
            <span className="small">
              <Mark ok={s.nodes.pack.action === 'ok'} label={`${s.nodes.pack.folder} (${s.nodes.pack.license}) · ${t(`install.action.${s.nodes.pack.action}`)}`} />
            </span>
            {s.nodes.broken_links.length > 0 && <span className="warn-text small">{t('install.broken_links', { names: s.nodes.broken_links.join(', ') })}</span>}
            {s.nodes.legacy_packs.length > 0 && <span className="warn-text small">{t('install.legacy_packs', { names: s.nodes.legacy_packs.join(', ') })}</span>}
          </>
        )}
      </section>

      <section className="col install-section">
        <div className="section-title">{t('install.models')}</div>
        <p className="faint small">{t('install.models_about')}</p>
        {!s.models.connected && <div className="warn-text small">{t('install.comfy_off')}</div>}
        {s.models.groups.map((group) => {
          const missing = group.items.filter((i) => !i.installed && !i.manual);
          const size = missing.reduce((n, i) => n + (i.size ?? 0), 0);
          return (
            <div key={group.id} className="compose-card">
              <div className="row">
                <strong className="grow">{group.name[lang] ?? group.name.ko}</strong>
                <button disabled={running || !s.models.connected || !missing.length} onClick={() => act('models', { items: [group.id] })}>
                  {missing.length ? t('install.download_n', { n: missing.length, size: gb(size) }) : t('install.all_there')}
                </button>
              </div>
              <span className="faint small">{group.about[lang] ?? group.about.ko}</span>
              <span className="small">
                {t('install.license')}:{' '}
                <a href={group.license.url} target="_blank" rel="noreferrer">
                  {group.license.name}
                </a>
              </span>
              {group.items.map((item) => (
                <div key={item.id} className="row small" title={item.installed ?? item.target ?? ''}>
                  <Mark ok={!!item.installed} label={item.file} />
                  <span className="faint">{item.size ? gb(item.size) : ''}</span>
                  {item.manual && !item.installed && (
                    <a href={item.manual} target="_blank" rel="noreferrer">
                      {t('install.manual', { folder: item.folder })}
                    </a>
                  )}
                </div>
              ))}
            </div>
          );
        })}
      </section>

      <section className="col install-section">
        <div className="row">
          <div className="section-title grow">{t('install.trainer')}</div>
          <button disabled={running} onClick={() => confirm(t('install.trainer_confirm')) && act('trainer')}>
            {tr.trainer_found && tr.venv && tr.patched ? t('install.trainer_again') : t('install.trainer_install')}
          </button>
        </div>
        <p className="faint small">{t('install.trainer_about', { commit: tr.version.commit.slice(0, 7), license: tr.version.license })}</p>
        <ToolsComing tools={s.tools} need={['uv', 'git']} />
        <span className="faint small mono">{tr.folder}</span>
        <div className="row small" style={{ flexWrap: 'wrap', gap: 12 }}>
          <Mark ok={tr.trainer_found} label="anima_lora" />
          <Mark ok={tr.venv && tr.python_found} label={t('install.trainer_python')} />
          <Mark ok={tr.patched} label={t('install.trainer_patch')} />
          <Mark ok={tr.lora_dir_found} label={t('install.trainer_lora_dir')} />
          <Mark ok={tr.bases.length > 0} label={t('install.trainer_models')} />
        </div>
        <span className="faint small">{t('install.trainer_settings')}</span>
      </section>

      {s.run && (
        <section className="col install-section">
          <div className="row">
            <div className="section-title grow">
              {t('install.log')} · {t(`install.${s.run.section}`)} · {t(`install.status.${s.run.status}`)}
            </div>
            {running && (
              <button className="danger" onClick={() => act('cancel')}>
                {t('common.cancel')}
              </button>
            )}
          </div>
          {s.run.error && <div className="error-text small">{msg(s.run.error)}</div>}
          <pre ref={logRef} className="lora-log mono small">
            {s.run.log.join('\n') || '…'}
          </pre>
        </section>
      )}
    </div>
  );
}
