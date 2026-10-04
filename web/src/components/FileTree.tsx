import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { ApiError, del, get, post, q } from '../api';
import { t, tm } from '../i18n';
import type { Tab, TreeEntry } from '../types';
import { useToast } from './Toasts';
import AuthoringDialog from './AuthoringDialog';
import RenameDialog from './RenameDialog';
import { ContextMenu, type MenuItem } from './ui';

const ICON: Record<string, string> = { main: '📜', start: '🎬', lorebook: '📄', character: '👤', jsx: '⚛', note: '🗒' };

type Pending = { parent: string; type: 'file' | 'folder' } | { rename: string } | null;

export default function FileTree({
  workId,
  activePath,
  open,
  renamePath,
  closeKey,
}: {
  workId: string;
  activePath: string | null;
  open: (tab: Tab) => void;
  renamePath: (from: string, to: string) => void;
  closeKey: (key: string) => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const tree = useQuery<TreeEntry[]>({ queryKey: ['tree', workId], queryFn: () => get(`/api/works/${workId}/tree`) });
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [menu, setMenu] = useState<{ x: number; y: number; entry: TreeEntry | null } | null>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [dragOver, setDragOver] = useState<string | null>(null);
  const [authoring, setAuthoring] = useState(false);
  const [renameText, setRenameText] = useState<string | null>(null);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['tree', workId] });
    qc.invalidateQueries({ queryKey: ['check', workId] });
  };
  const fail = (err: unknown) => toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });

  async function submitPending(name: string) {
    const value = name.trim();
    const current = pending;
    setPending(null);
    if (!value || !current) return;
    try {
      if ('rename' in current) {
        const parent = current.rename.includes('/') ? current.rename.slice(0, current.rename.lastIndexOf('/') + 1) : '';
        const to = parent + value;
        if (to === current.rename) return;
        await post(`/api/works/${workId}/move`, { from: current.rename, to });
        renamePath(current.rename, to);
      } else if (current.type === 'folder') {
        await post(`/api/works/${workId}/folder`, { path: join(current.parent, value) });
      } else {
        const item = await post(`/api/works/${workId}/file`, { path: join(current.parent, value) });
        open({ type: 'item', path: item.path });
      }
      refresh();
    } catch (err) {
      fail(err);
    }
  }

  async function remove(entry: TreeEntry) {
    const extras = entry.kind === 'character' || entry.kind === 'jsx';
    if (!confirm(t('tree.delete_confirm', { name: entry.name }))) return;
    const withExtras = extras && confirm(t(entry.kind === 'character' ? 'tree.delete_image_too' : 'tree.delete_props_too'));
    try {
      await del(`/api/works/${workId}/file?path=${q(entry.path)}&extras=${withExtras ? 1 : 0}`);
      closeKey(`item:${entry.path}`);
      refresh();
      qc.invalidateQueries({ queryKey: ['work-trash', workId] });
    } catch (err) {
      fail(err);
    }
  }

  async function drop(target: TreeEntry | null, source: string) {
    setDragOver(null);
    const folder = target ? (target.type === 'folder' ? target.path : parentOf(target.path)) : '';
    const name = source.split('/').pop()!;
    const to = join(folder, name);
    if (to === source || to.startsWith(`${source}/`)) return;
    try {
      await post(`/api/works/${workId}/move`, { from: source, to });
      renamePath(source, to);
      refresh();
    } catch (err) {
      fail(err);
    }
  }

  const menuFor = (entry: TreeEntry | null): MenuItem[] => {
    const folder = entry ? (entry.type === 'folder' ? entry.path : parentOf(entry.path)) : '';
    return [
      { label: t('tree.new_file'), run: () => setPending({ parent: folder, type: 'file' }) },
      { label: t('tree.new_folder'), run: () => setPending({ parent: folder, type: 'folder' }) },
      ...(entry
        ? [
            null,
            { label: t('tree.rename'), run: () => setPending({ rename: entry.path }) },
            ...(entry.type === 'item' ? [{ label: t('rename.from_tree'), run: () => setRenameText(entry.name.replace(/.(md|jsx)$/, '')) }] : []),
            { label: t('tree.copy_path'), run: () => navigator.clipboard.writeText(entry.path) },
            null,
            { label: t('tree.delete'), danger: true, run: () => remove(entry) },
          ]
        : []),
    ];
  };

  function render(entries: TreeEntry[], depth: number, parent: string): React.ReactNode {
    const rows: React.ReactNode[] = [];
    if (pending && 'parent' in pending && pending.parent === parent) {
      rows.push(
        <div key="__new" className="tree-row" style={{ paddingLeft: 8 + depth * 14 }}>
          {pending.type === 'folder' ? '📁' : '📄'}
          <NameInput onDone={submitPending} placeholder={pending.type === 'file' ? t('tree.file_hint') : ''} />
        </div>,
      );
    }
    for (const entry of entries) {
      const isFolder = entry.type === 'folder';
      const isCollapsed = collapsed[entry.path];
      const renaming = pending && 'rename' in pending && pending.rename === entry.path;
      rows.push(
        <div
          key={entry.path}
          className={[
            'tree-row',
            entry.path === activePath ? 'sel' : '',
            entry.enabled === false ? 'disabled' : '',
            entry.type === 'file' ? 'file' : '',
            dragOver === entry.path ? 'drop' : '',
          ].join(' ')}
          style={{ paddingLeft: 8 + depth * 14 }}
          draggable={!renaming}
          onDragStart={(e) => e.dataTransfer.setData('text/x-atelierx-path', entry.path)}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(entry.path);
          }}
          onDragLeave={() => setDragOver(null)}
          onDrop={(e) => {
            e.preventDefault();
            e.stopPropagation();
            drop(entry, e.dataTransfer.getData('text/x-atelierx-path'));
          }}
          onClick={() => {
            if (isFolder) setCollapsed((c) => ({ ...c, [entry.path]: !c[entry.path] }));
            else if (entry.type === 'item') open({ type: 'item', path: entry.path });
          }}
          onContextMenu={(e) => {
            e.preventDefault();
            e.stopPropagation();
            setMenu({ x: e.clientX, y: e.clientY, entry });
          }}
          onKeyDown={(e) => e.key === 'F2' && setPending({ rename: entry.path })}
          tabIndex={0}
        >
          <span style={{ width: 12, color: 'var(--text-3)' }}>{isFolder ? (isCollapsed ? '▸' : '▾') : ''}</span>
          <span>{isFolder ? '📁' : entry.kind ? ICON[entry.kind] : '·'}</span>
          {renaming ? (
            <NameInput initial={entry.name} onDone={submitPending} />
          ) : (
            <span className="grow" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {entry.name}
            </span>
          )}
          {entry.meta_error && <span style={{ color: 'var(--danger)' }}>!</span>}
          {entry.id && <span className="faint">{entry.id}</span>}
        </div>,
      );
      if (isFolder && !isCollapsed) rows.push(render(entry.children ?? [], depth + 1, entry.path));
    }
    return rows;
  }

  return (
    <div
      style={{ minHeight: '100%' }}
      onContextMenu={(e) => {
        e.preventDefault();
        setMenu({ x: e.clientX, y: e.clientY, entry: null });
      }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        drop(null, e.dataTransfer.getData('text/x-atelierx-path'));
      }}
    >
      <div className="side-head">
        <span className="grow">{t('panel.files')}</span>
        <button className="ghost" title={t('authoring.title')} onClick={() => setAuthoring(true)}>
          ✨
        </button>
        <button className="ghost" title={t('tree.new_file')} onClick={() => setPending({ parent: '', type: 'file' })}>
          ＋📄
        </button>
        <button className="ghost" title={t('tree.new_folder')} onClick={() => setPending({ parent: '', type: 'folder' })}>
          ＋📁
        </button>
      </div>
      <div className="tree">
        {tree.data && tree.data.length === 0 && !pending && (
          <div className="empty">
            <p>{t('tree.empty')}</p>
            <button onClick={() => setAuthoring(true)}>✨ {t('authoring.title')}</button>
          </div>
        )}
        {tree.data && render(tree.data, 0, '')}
      </div>
      {renameText !== null && <RenameDialog workId={workId} initial={renameText} renamePath={renamePath} onClose={() => setRenameText(null)} />}
      {authoring && <AuthoringDialog workId={workId} onClose={() => setAuthoring(false)} />}
      {menu && <ContextMenu x={menu.x} y={menu.y} items={menuFor(menu.entry)} onClose={() => setMenu(null)} />}
    </div>
  );
}

function NameInput({ initial = '', placeholder, onDone }: { initial?: string; placeholder?: string; onDone: (value: string) => void }) {
  const [value, setValue] = useState(initial);
  const done = useRef(false);
  const finish = (result: string) => {
    if (done.current) return;
    done.current = true;
    onDone(result);
  };
  return (
    <input
      autoFocus
      className="grow"
      value={value}
      placeholder={placeholder}
      onClick={(e) => e.stopPropagation()}
      onChange={(e) => setValue(e.target.value)}
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === 'Enter') finish(value);
        if (e.key === 'Escape') finish('');
      }}
      onBlur={() => finish(value)}
      onFocus={(e) => {
        const dot = e.target.value.lastIndexOf('.');
        e.target.setSelectionRange(0, dot > 0 ? dot : e.target.value.length);
      }}
    />
  );
}

function join(parent: string, name: string) {
  return parent ? `${parent}/${name}` : name;
}

function parentOf(path: string) {
  return path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '';
}
