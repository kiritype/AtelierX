import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { del, get, patch, post } from '../api';
import { t } from '../i18n';
import type { Tab, TreeEntry, WorkInfo } from '../types';
import FileTree from './FileTree';
import RenameDialog from './RenameDialog';
import { useToast } from './Toasts';

export type PanelKey = 'files' | 'search' | 'image' | 'drafts' | 'history' | 'trash';

type Props = {
  panel: PanelKey;
  workId: string;
  info: WorkInfo;
  activePath: string | null;
  open: (tab: Tab) => void;
  closeKey: (key: string) => void;
  renamePath: (from: string, to: string) => void;
};

export default function Panels(props: Props) {
  switch (props.panel) {
    case 'files':
      return <FileTree workId={props.workId} activePath={props.activePath} open={props.open} renamePath={props.renamePath} closeKey={props.closeKey} />;
    case 'search':
      return <SearchPanel {...props} />;
    case 'image':
      return <ImagePanel {...props} />;
    case 'drafts':
      return <DraftsPanel {...props} />;
    case 'history':
      return <HistoryPanel {...props} />;
    case 'trash':
      return <TrashPanel {...props} />;
    default:
      return (
        <>
          <div className="side-head">{t(`panel.${props.panel}`)}</div>
          <div className="empty">{t(`panel.${props.panel}_later`)}</div>
        </>
      );
  }
}

function SearchPanel({ workId, open, renamePath }: Props) {
  const [query, setQuery] = useState('');
  const [renaming, setRenaming] = useState(false);
  const [submitted, setSubmitted] = useState('');
  const hits = useQuery({
    queryKey: ['search', workId, submitted],
    queryFn: () => get(`/api/works/${workId}/search?q=${encodeURIComponent(submitted)}`),
    enabled: !!submitted,
  });
  return (
    <>
      <div className="side-head">
        <span className="grow">{t('panel.search')}</span>
        <button className="ghost" title={t('rename.title')} onClick={() => setRenaming(true)}>
          ⇄
        </button>
      </div>
      {renaming && <RenameDialog workId={workId} initial={query} renamePath={renamePath} onClose={() => setRenaming(false)} />}
      <div style={{ padding: 8 }}>
        <input
          autoFocus
          style={{ width: '100%' }}
          placeholder={t('search.placeholder')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && setSubmitted(query.trim())}
        />
      </div>
      {(hits.data ?? []).map((hit: any) => (
        <div key={hit.path} style={{ padding: '4px 8px', cursor: 'pointer' }} onClick={() => open({ type: 'item', path: hit.path })}>
          <strong>{hit.name}</strong> <span className="faint">{hit.path}</span>
          {hit.lines.map(([n, line]: [number, string]) => (
            <div key={n} className="faint mono" style={{ fontSize: 11, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {n}: {line}
            </div>
          ))}
        </div>
      ))}
      {submitted && hits.data?.length === 0 && <div className="empty">{t('search.none')}</div>}
    </>
  );
}

function flatten(entries: TreeEntry[]): TreeEntry[] {
  return entries.flatMap((e) => (e.type === 'folder' ? flatten(e.children ?? []) : [e]));
}

function ImagePanel({ workId, open }: Props) {
  const tree = useQuery<TreeEntry[]>({ queryKey: ['tree', workId], queryFn: () => get(`/api/works/${workId}/tree`) });
  const characters = flatten(tree.data ?? []).filter((e) => e.kind === 'character');
  return (
    <>
      <div className="side-head">{t('panel.image')}</div>
      {characters.length === 0 && <div className="empty">{t('image.no_characters')}</div>}
      {characters.map((c) => (
        <div key={c.path} className="tree-row" onClick={() => open({ type: 'item', path: c.path })}>
          👤 <span className="grow">{c.name.replace(/\.md$/, '')}</span> <span className="faint">{c.id}</span>
        </div>
      ))}
      <div className="empty faint">{t('image.library_later')}</div>
    </>
  );
}

function DraftsPanel({ workId, open }: Props) {
  const drafts = useQuery({ queryKey: ['drafts-all', workId], queryFn: () => get(`/api/works/${workId}/drafts`) });
  return (
    <>
      <div className="side-head">{t('panel.drafts')}</div>
      {(drafts.data ?? []).length === 0 && <div className="empty">{t('drafts.empty')}</div>}
      {(drafts.data ?? []).map((d: any) => (
        <div key={d.id} className="list-row" style={{ cursor: 'pointer' }} onClick={() => open({ type: 'review', draft: d.id })}>
          <span className="grow">
            {t(`draft.kind.${d.kind}`)} · {d.target.path?.split('/').pop()}
            <div className="faint">{d.created_at?.slice(5, 16).replace('T', ' ')}</div>
          </span>
          <span className={d.status === 'pending' ? 'badge' : 'faint'}>{t(`draft.status.${d.status}`)}</span>
        </div>
      ))}
    </>
  );
}

function HistoryPanel({ workId, open }: Props) {
  const qc = useQueryClient();
  const toast = useToast();
  const snaps = useQuery({ queryKey: ['snapshots', workId], queryFn: () => get(`/api/works/${workId}/snapshots`) });
  const [filter, setFilter] = useState('all');
  const list = (snaps.data ?? []).filter((s: any) => filter === 'all' || (filter === 'manual' ? s.reason === 'manual' : !!s.release));
  return (
    <>
      <div className="side-head">
        <span className="grow">{t('panel.history')}</span>
        <button
          className="ghost"
          onClick={async () => {
            const label = prompt(t('history.label_prompt')) ?? undefined;
            await post(`/api/works/${workId}/snapshots`, { reason: 'manual', label });
            qc.invalidateQueries({ queryKey: ['snapshots', workId] });
            toast({ text: t('history.created') });
          }}
        >
          ＋
        </button>
      </div>
      <div style={{ padding: 8 }}>
        <select value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: '100%' }}>
          <option value="all">{t('history.all')}</option>
          <option value="manual">{t('history.manual')}</option>
          <option value="release">{t('history.release')}</option>
        </select>
      </div>
      {list.length === 0 && <div className="empty">{t('history.empty')}</div>}
      {list.map((s: any) => (
        <div key={s.id} className="list-row" style={{ cursor: 'pointer', alignItems: 'flex-start' }} onClick={() => open({ type: 'compare', snapshot: s.id })}>
          <span className="grow">
            {s.created_at?.slice(5, 16).replace('T', ' ')} · {t(`reason.${s.reason}`)}
            {s.label && <div className="muted">{s.label}</div>}
            {s.release && <span className="chip accent">🚀 {s.release.note}</span>}
          </span>
          <button
            className="ghost"
            title={t('history.mark_release')}
            onClick={async (e) => {
              e.stopPropagation();
              const note = s.release ? '' : prompt(t('history.release_prompt')) || '';
              if (!s.release && !note) return;
              await patch(`/api/works/${workId}/snapshots/${s.id}`, { release: note || null });
              qc.invalidateQueries({ queryKey: ['snapshots', workId] });
            }}
          >
            🚀
          </button>
        </div>
      ))}
    </>
  );
}

function TrashPanel({ workId }: Props) {
  const qc = useQueryClient();
  const trash = useQuery({ queryKey: ['work-trash', workId], queryFn: () => get(`/api/works/${workId}/trash`) });
  const reload = () => {
    qc.invalidateQueries({ queryKey: ['work-trash', workId] });
    qc.invalidateQueries({ queryKey: ['tree', workId] });
  };
  return (
    <>
      <div className="side-head">
        <span className="grow">{t('panel.trash')}</span>
        {(trash.data ?? []).length > 0 && (
          <button
            className="ghost danger"
            onClick={async () => {
              if (!confirm(t('trash.empty_confirm'))) return;
              await del(`/api/works/${workId}/trash`);
              reload();
            }}
          >
            {t('trash.empty_all')}
          </button>
        )}
      </div>
      {(trash.data ?? []).length === 0 && <div className="empty">{t('trash.empty')}</div>}
      {(trash.data ?? []).map((entry: any) => (
        <div key={entry.id} className="list-row" style={{ alignItems: 'flex-start' }}>
          <span className="grow">
            {entry.paths.map((p: string) => (
              <div key={p}>{p}</div>
            ))}
            <div className="faint">{entry.deleted_at?.slice(5, 16).replace('T', ' ')}</div>
          </span>
          <button
            onClick={async () => {
              await post(`/api/works/${workId}/trash/${entry.id}/restore`);
              reload();
            }}
          >
            {t('trash.restore')}
          </button>
          <button
            className="danger"
            onClick={async () => {
              if (!confirm(t('trash.purge_confirm'))) return;
              await del(`/api/works/${workId}/trash/${entry.id}`);
              reload();
            }}
          >
            ✕
          </button>
        </div>
      ))}
    </>
  );
}
