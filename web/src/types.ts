export type Kind = 'main' | 'start' | 'lorebook' | 'character' | 'jsx' | 'note';

export const KINDS: Kind[] = ['main', 'start', 'lorebook', 'character', 'jsx', 'note'];

export type WorkCard = {
  id: string;
  name: string;
  tags: string[];
  scale: string;
  language: string;
  items: number;
  size: number;
  updated_at: string;
};

// GET /api/works: the cards and the ID the next new work would get.
export type WorkList = { works: WorkCard[]; suggest_id: string };

export type TreeEntry = {
  type: 'folder' | 'item' | 'file';
  name: string;
  path: string;
  kind?: Kind | null;
  id?: string | null;
  enabled?: boolean | null;
  meta_error?: string | null;
  children?: TreeEntry[];
};

export type Item = {
  path: string;
  name: string;
  meta: Record<string, any>;
  kind: Kind;
  body: string;
  hash: string;
  meta_error: string | null;
  size: number;
  // Places that use this item's ID (image, jsx, char, relations); the ID cannot change while any remain.
  id_links?: string[];
};

export type Issue = {
  level: 'error' | 'warning' | 'info';
  path: string | null;
  message: { key: string; text: string; values?: Record<string, unknown> };
};

export type Job = {
  id: string;
  kind: string;
  title: string;
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled';
  progress: number;
  result: any;
  // A server message: translated with tm() (key and values), its English text otherwise.
  error: { key: string; text: string; values?: Record<string, unknown> } | null;
  work_id: string | null;
};

// GET /api/works/{wid}/search: matching items and their matching lines (line number, text).
export type SearchHit = { path: string; name: string; lines: [number, string][] };

// GET /api/works/{wid}/drafts
export type DraftSummary = { id: string; kind: string; target: { path?: string; [key: string]: unknown }; status: string; created_at: string };

// GET /api/works/{wid}/snapshots (09-snapshots); a release mark keeps the snapshot from pruning.
export type SnapshotSummary = {
  id: string;
  reason: string;
  label?: string | null;
  created_at: string;
  release?: { note: string; at: string } | null;
  file_count: number;
};

// GET /api/works/{wid}/trash and /api/trash: one deleted bundle.
export type TrashBundle = { id: string; paths: string[]; deleted_at: string };

// GET /api/samples
export type SampleSummary = { name: string; scale: string; tags: string[] };

// GET /api/platforms (platform presets, decision 0009), as the lists read them.
export type PlatformPresetSummary = { id: string; name: string; readonly?: boolean };

export type WorkInfo = {
  name: string;
  doc: Record<string, any>;
  effective: { linked: string[]; values: Record<string, any>; sources: Record<string, any> };
  presets: { id: string; name: string; readonly: boolean }[];
};

export type Tab =
  | { type: 'item'; path: string }
  | { type: 'work-settings' }
  | { type: 'settings'; section?: string; at?: number }
  | { type: 'review'; draft: string }
  | { type: 'compare'; snapshot: string; label?: string }
  | { type: 'relations' }
  | { type: 'glossary' }
  | { type: 'image'; view: ImageView; characterId?: string; outfitId?: string };

export type ImageView = 'library' | 'presets' | 'models' | 'board' | 'generate' | 'queue' | 'lab' | 'gallery' | 'tools' | 'lora';

// "10-06 03:56" from a snapshot ID such as 20261006T035650966-37f8, for titles that should not show the raw ID.
export function snapshotTime(id: string): string {
  const m = /^\d{4}(\d{2})(\d{2})T(\d{2})(\d{2})/.exec(id);
  return m ? `${m[1]}-${m[2]} ${m[3]}:${m[4]}` : id;
}

export function tabKey(tab: Tab): string {
  switch (tab.type) {
    case 'item':
      return `item:${tab.path}`;
    case 'review':
      return `review:${tab.draft}`;
    case 'compare':
      return `compare:${tab.snapshot}`;
    case 'image':
      return `image:${tab.view}${tab.characterId ? `:${tab.characterId}:${tab.outfitId ?? ''}` : ''}`;
    default:
      return tab.type;
  }
}
