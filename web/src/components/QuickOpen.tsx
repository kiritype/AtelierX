import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { get } from '../api';
import { t } from '../i18n';
import type { TreeEntry } from '../types';

function flatten(entries: TreeEntry[]): TreeEntry[] {
  return entries.flatMap((e) => (e.type === 'folder' ? flatten(e.children ?? []) : e.type === 'item' ? [e] : []));
}

export default function QuickOpen({ workId, onClose, onOpen }: { workId: string; onClose: () => void; onOpen: (path: string) => void }) {
  const tree = useQuery<TreeEntry[]>({ queryKey: ['tree', workId], queryFn: () => get(`/api/works/${workId}/tree`) });
  const [query, setQuery] = useState('');
  const [index, setIndex] = useState(0);
  const items = flatten(tree.data ?? []).filter((e) => {
    const s = query.toLowerCase();
    return !s || e.path.toLowerCase().includes(s) || (e.id ?? '').toLowerCase().includes(s);
  });
  const choose = (entry?: TreeEntry) => {
    if (!entry) return;
    onOpen(entry.path);
    onClose();
  };
  return (
    <div className="overlay" style={{ alignItems: 'flex-start', paddingTop: 80 }} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" style={{ width: 520, padding: 8, gap: 4 }}>
        <input
          autoFocus
          placeholder={t('editor.quick_open_hint')}
          value={query}
          onChange={(e) => (setQuery(e.target.value), setIndex(0))}
          onKeyDown={(e) => {
            if (e.key === 'Escape') onClose();
            if (e.key === 'ArrowDown') setIndex((i) => Math.min(i + 1, items.length - 1));
            if (e.key === 'ArrowUp') setIndex((i) => Math.max(i - 1, 0));
            if (e.key === 'Enter') choose(items[index]);
          }}
        />
        <div style={{ maxHeight: 360, overflow: 'auto' }}>
          {items.slice(0, 50).map((e, i) => (
            <div key={e.path} className={`tree-row${i === index ? ' sel' : ''}`} onClick={() => choose(e)}>
              <span className="grow">{e.path}</span>
              <span className="faint">{e.id}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
