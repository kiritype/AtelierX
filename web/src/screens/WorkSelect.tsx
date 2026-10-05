import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { ApiError, del, get, patch, post } from '../api';
import { useToast } from '../components/Toasts';
import { ChipsInput, ContextMenu, Dialog, formatBytes, type MenuItem } from '../components/ui';
import { t, tm } from '../i18n';
import type { WorkCard } from '../types';
import { Icon } from '../components/icons';
import { useHelp, useStartupUpdateCheck } from '../components/Help';
import { MenuButton } from '../components/MenuBar';

export default function WorkSelect({ onOpen, onLock }: { onOpen: (id: string) => void; onLock: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const works = useQuery({ queryKey: ['works'], queryFn: () => get('/api/works') });
  const help = useHelp();
  const appSettings = useQuery<{ update_check_on_start?: boolean }>({ queryKey: ['settings'], queryFn: () => get('/api/settings') });
  useStartupUpdateCheck(!!appSettings.data?.update_check_on_start);
  const ui = useQuery({ queryKey: ['ui-state'], queryFn: () => get('/api/ui-state') });
  const [search, setSearch] = useState('');
  const [dialog, setDialog] = useState<null | 'new' | 'samples' | 'trash' | { dup: WorkCard } | { rename: WorkCard }>(
    null,
  );
  const [menu, setMenu] = useState<{ x: number; y: number; work: WorkCard } | null>(null);

  const refresh = () => qc.invalidateQueries({ queryKey: ['works'] });
  const fail = (err: unknown) => toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });

  const lastWork = ui.data?.last_work;
  const list: WorkCard[] = (works.data?.works ?? [])
    .filter((w: WorkCard) => {
      const s = search.toLowerCase();
      return !s || w.name.toLowerCase().includes(s) || w.id.toLowerCase().includes(s) || w.tags.some((x) => x.toLowerCase().includes(s));
    })
    .sort((a: WorkCard, b: WorkCard) => (a.id === lastWork ? -1 : b.id === lastWork ? 1 : (b.updated_at ?? '').localeCompare(a.updated_at ?? '')));

  const menuItems = (work: WorkCard): MenuItem[] => [
    { label: t('works.open'), run: () => onOpen(work.id) },
    { label: t('works.rename'), run: () => setDialog({ rename: work }) },
    { label: t('works.duplicate'), run: () => setDialog({ dup: work }) },
    null,
    {
      label: t('works.delete'),
      danger: true,
      run: async () => {
        if (!confirm(t('works.delete_confirm', { name: work.name }))) return;
        await del(`/api/works/${work.id}`).catch(fail);
        refresh();
      },
    },
  ];

  return (
    <div className="select-page">
      <div className="row">
        <h2 className="grow">AtelierX</h2>
        <MenuButton className="ghost" label={t('menu.help')} items={help.entries} />
        <button className="ghost" onClick={() => setDialog('trash')}>
          <Icon name="trash" /> {t('works.trash')}
        </button>
        <button
          className="ghost"
          onClick={async () => {
            await post('/api/auth/lock');
            onLock();
          }}
        >
          <Icon name="lock" /> {t('common.lock')}
        </button>
      </div>
      <div className="row">
        <input className="grow" placeholder={t('works.search')} value={search} onChange={(e) => setSearch(e.target.value)} />
        <button onClick={() => setDialog('samples')}>{t('works.samples')}</button>
        <button className="primary" onClick={() => setDialog('new')}>
          {t('works.new')}
        </button>
      </div>
      {works.data && list.length === 0 && !search && (
        <div className="empty">
          <p>{t('works.empty')}</p>
          <div className="row" style={{ justifyContent: 'center' }}>
            <button onClick={() => setDialog('samples')}>{t('works.samples')}</button>
            <button className="primary" onClick={() => setDialog('new')}>
              {t('works.new')}
            </button>
          </div>
        </div>
      )}
      <div className="cards">
        {list.map((work) => (
          <div key={work.id} className="work-card" onClick={() => onOpen(work.id)}>
            <button
              className="ghost menu"
              onClick={(e) => {
                e.stopPropagation();
                setMenu({ x: e.clientX, y: e.clientY, work });
              }}
            >
              ⋯
            </button>
            <strong>{work.name}</strong>
            <span className="faint">
              {work.id} · {t(`scale.${work.scale}`)}
            </span>
            <div className="row" style={{ flexWrap: 'wrap', gap: 4 }}>
              {work.tags.map((tag) => (
                <span key={tag} className="chip">
                  {tag}
                </span>
              ))}
            </div>
            <span className="muted">{t('works.card_stats', { n: work.items, size: formatBytes(work.size) })}</span>
          </div>
        ))}
      </div>
      {menu && <ContextMenu x={menu.x} y={menu.y} items={menuItems(menu.work)} onClose={() => setMenu(null)} />}
      {dialog === 'new' && (
        <NewWorkDialog
          suggestId={works.data?.suggest_id}
          onClose={() => setDialog(null)}
          onCreated={(id) => {
            refresh();
            onOpen(id);
          }}
        />
      )}
      {dialog === 'samples' && (
        <SamplesDialog
          onClose={() => setDialog(null)}
          onInstalled={(id) => {
            refresh();
            onOpen(id);
          }}
        />
      )}
      {dialog === 'trash' && <WorksTrashDialog onClose={() => setDialog(null)} onChanged={refresh} />}
      {dialog && typeof dialog === 'object' && 'dup' in dialog && (
        <NameDialog
          title={t('works.duplicate')}
          initial={`${dialog.dup.name} 복사본`}
          onClose={() => setDialog(null)}
          onSubmit={async (name) => {
            const card = await post(`/api/works/${dialog.dup.id}/duplicate`, { name });
            refresh();
            toast({ text: t('works.duplicated', { name: card.name }) });
          }}
        />
      )}
      {dialog && typeof dialog === 'object' && 'rename' in dialog && (
        <NameDialog
          title={t('works.rename')}
          initial={dialog.rename.name}
          onClose={() => setDialog(null)}
          onSubmit={async (name) => {
            await patch(`/api/works/${dialog.rename.id}`, { name });
            refresh();
          }}
        />
      )}
      {help.element}
    </div>
  );
}

function NameDialog({
  title,
  initial,
  onClose,
  onSubmit,
}: {
  title: string;
  initial: string;
  onClose: () => void;
  onSubmit: (name: string) => Promise<void>;
}) {
  const [name, setName] = useState(initial);
  const [error, setError] = useState('');
  return (
    <Dialog
      title={title}
      onClose={onClose}
      actions={
        <button
          className="primary"
          onClick={async () => {
            try {
              await onSubmit(name.trim());
              onClose();
            } catch (err) {
              setError(err instanceof ApiError ? tm(err.msg) : String(err));
            }
          }}
        >
          {t('common.ok')}
        </button>
      }
    >
      <label>
        {t('works.name')}
        <input autoFocus value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      {error && <div className="error-text">{error}</div>}
    </Dialog>
  );
}

function NewWorkDialog({
  suggestId,
  onClose,
  onCreated,
}: {
  suggestId?: string;
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => get('/api/settings') });
  const presets = useQuery({ queryKey: ['platforms'], queryFn: () => get('/api/platforms') });
  const [name, setName] = useState('');
  const [id, setId] = useState('');
  const [tags, setTags] = useState<string[] | null>(null);
  const [scale, setScale] = useState('single');
  const [language, setLanguage] = useState('ko');
  const [error, setError] = useState('');
  const presetIds = new Set((presets.data ?? []).map((p: any) => p.id));
  const defaultTag = settings.data?.default_platform_preset;
  const shownTags = tags ?? (defaultTag ? [defaultTag] : []);

  async function create() {
    try {
      const card = await post('/api/works', { name: name.trim(), id: id.trim() || null, tags: shownTags, scale, language });
      onClose();
      onCreated(card.id);
    } catch (err) {
      setError(err instanceof ApiError ? tm(err.msg) : String(err));
    }
  }

  return (
    <Dialog
      title={t('works.new')}
      onClose={onClose}
      actions={
        <button className="primary" disabled={!name.trim()} onClick={create}>
          {t('works.create')}
        </button>
      }
    >
      <div className="row">
        <label className="grow">
          {t('works.name')}
          <input autoFocus value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label style={{ width: 110 }}>
          ID
          <input value={id} placeholder={suggestId} onChange={(e) => setId(e.target.value)} />
        </label>
      </div>
      <label>
        {t('works.tags')}
        <ChipsInput values={shownTags} onChange={setTags} placeholder={t('works.tags_hint')} accent={(v) => presetIds.has(v)} />
        <span className="faint">{t('works.tags_note')}</span>
      </label>
      <div className="row">
        <label className="grow">
          {t('works.scale')}
          <select value={scale} onChange={(e) => setScale(e.target.value)}>
            {['single', 'ensemble', 'simulation'].map((s) => (
              <option key={s} value={s}>
                {t(`scale.${s}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="grow">
          {t('works.language')}
          <select value={language} onChange={(e) => setLanguage(e.target.value)}>
            <option value="ko">한국어</option>
            <option value="en">English</option>
          </select>
        </label>
      </div>
      {error && <div className="error-text">{error}</div>}
    </Dialog>
  );
}

function SamplesDialog({ onClose, onInstalled }: { onClose: () => void; onInstalled: (id: string) => void }) {
  const samples = useQuery({ queryKey: ['samples'], queryFn: () => get('/api/samples') });
  const [error, setError] = useState('');
  return (
    <Dialog title={t('works.samples')} onClose={onClose}>
      <p className="muted">{t('works.samples_note')}</p>
      {(samples.data ?? []).map((sample: any) => (
        <div key={sample.name} className="list-row">
          <span className="grow">
            <strong>{sample.name}</strong> <span className="faint">{t(`scale.${sample.scale}`)}</span>
          </span>
          <button
            onClick={async () => {
              try {
                const card = await post(`/api/samples/${sample.name}/install`);
                onClose();
                onInstalled(card.id);
              } catch (err) {
                setError(err instanceof ApiError ? tm(err.msg) : String(err));
              }
            }}
          >
            {t('works.install_sample')}
          </button>
        </div>
      ))}
      {error && <div className="error-text">{error}</div>}
    </Dialog>
  );
}

function WorksTrashDialog({ onClose, onChanged }: { onClose: () => void; onChanged: () => void }) {
  const qc = useQueryClient();
  const trash = useQuery({ queryKey: ['data-trash'], queryFn: () => get('/api/trash') });
  const reload = () => {
    qc.invalidateQueries({ queryKey: ['data-trash'] });
    onChanged();
  };
  return (
    <Dialog title={t('works.trash')} onClose={onClose}>
      {(trash.data ?? []).length === 0 && <div className="empty">{t('trash.empty')}</div>}
      {(trash.data ?? []).map((entry: any) => (
        <div key={entry.id} className="list-row">
          <span className="grow">
            {entry.paths.join(', ')} <span className="faint">{entry.deleted_at?.slice(0, 16)}</span>
          </span>
          <button
            onClick={async () => {
              await post(`/api/trash/${entry.id}/restore`);
              reload();
            }}
          >
            {t('trash.restore')}
          </button>
          <button
            className="danger"
            onClick={async () => {
              if (!confirm(t('trash.purge_confirm'))) return;
              await del(`/api/trash/${entry.id}`);
              reload();
            }}
          >
            {t('trash.purge')}
          </button>
        </div>
      ))}
    </Dialog>
  );
}
