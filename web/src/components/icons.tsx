// One icon set (Lucide, ISC license) with one stroke width, so light and dark themes look alike.
import {
  BookA,
  BookOpen,
  Braces,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  CircleX,
  Clapperboard,
  File,
  FilePlus,
  Files,
  FileText,
  Folder,
  FolderPlus,
  History,
  Hourglass,
  Image,
  Inbox,
  Info,
  Lock,
  Pencil,
  Network,
  PanelRight,
  Pin,
  Rocket,
  ScrollText,
  Search,
  Settings,
  Sparkles,
  StickyNote,
  Trash2,
  TriangleAlert,
  UserRound,
  X,
  type LucideIcon,
} from 'lucide-react';

export const ICONS = {
  files: Files,
  search: Search,
  relations: Network,
  glossary: BookA,
  image: Image,
  drafts: Inbox,
  history: History,
  trash: Trash2,
  aux: PanelRight,
  jobs: Hourglass,
  settings: Settings,
  lock: Lock,
  edit: Pencil,
  pin: Pin,
  close: X,
  folder: Folder,
  file: File,
  newFile: FilePlus,
  newFolder: FolderPlus,
  expand: ChevronRight,
  collapse: ChevronDown,
  authoring: Sparkles,
  character: UserRound,
  release: Rocket,
  ok: CircleCheck,
  error: CircleX,
  warning: TriangleAlert,
  info: Info,
  menu: ChevronDown,
} satisfies Record<string, LucideIcon>;

// File kinds (decision 0006) keep one icon each in the tree and the editor.
export const KIND_ICONS: Record<string, LucideIcon> = {
  main: ScrollText,
  start: Clapperboard,
  lorebook: BookOpen,
  character: UserRound,
  jsx: Braces,
  note: StickyNote,
};

export type IconName = keyof typeof ICONS;

export function Icon({ name, size = 16, className }: { name: IconName; size?: number; className?: string }) {
  const Glyph = ICONS[name];
  return <Glyph size={size} strokeWidth={1.75} className={['icon', className].filter(Boolean).join(' ')} aria-hidden />;
}

export function KindIcon({ kind, size = 16 }: { kind?: string | null; size?: number }) {
  const Glyph = (kind && KIND_ICONS[kind]) || FileText;
  return <Glyph size={size} strokeWidth={1.75} className="icon" aria-hidden />;
}
