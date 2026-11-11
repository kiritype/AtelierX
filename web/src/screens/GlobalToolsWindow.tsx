import { lazy, Suspense, useState, useSyncExternalStore } from 'react';
import { AppMark } from '../components/AppMark';
import { Icon } from '../components/icons';
import { TabScope } from '../components/Unsaved';
import { Loading } from '../components/ui';
import { t } from '../i18n';
import { UnsavedRegistry } from '../lib/unsaved';

const StyleExplorer = lazy(() => import('../components/image/StyleExplorer'));
const ImageQueue = lazy(() => import('../components/image/ImageQueue'));
const PresetExplorer = lazy(() => import('../components/image/PresetExplorer'));
const AppSettings = lazy(() => import('../components/AppSettings'));

type View = 'explorer' | 'queue' | 'presets' | 'settings';
const views: { view: View; label: string }[] = [
  { view: 'explorer', label: 'image_menu.explorer' },
  { view: 'queue', label: 'image_menu.queue' },
  { view: 'presets', label: 'image_menu.presets' },
  { view: 'settings', label: 'window.settings' },
];

export default function GlobalToolsWindow({ workId, onClose }: { workId?: string; onClose: () => void }) {
  const [view, setView] = useState<View>('explorer');
  const [visited, setVisited] = useState<View[]>(['explorer']);
  const [unsaved] = useState(() => new UnsavedRegistry());
  useSyncExternalStore(unsaved.subscribe, unsaved.snapshot);

  const canLeave = (alreadyChecked?: View) => {
    const dirty = views.filter(({ view }) => view !== alreadyChecked && unsaved.dirty(view));
    return !dirty.length || confirm(t('tabs.close_unsaved', { names: dirty.map(({ label }) => t(label)).join(', ') }));
  };
  const close = () => {
    if (canLeave()) onClose();
  };
  const openGenerate = () => {
    onClose();
    window.dispatchEvent(new Event('atelierx:open-image-generate'));
  };
  const openView = (next: View) => {
    setVisited((current) => current.includes(next) ? current : [...current, next]);
    setView(next);
  };

  return (
    <div className="window" aria-label={t('menu.tools')} style={{ gridTemplateRows: '44px minmax(0, 1fr)' }}>
      <div className="topbar">
        <span className="topbar-mark" title="AtelierX"><AppMark size={20} /></span>
        <strong style={{ padding: '4px 8px' }}>{t('menu.tools')}</strong>
        <span className="grow" />
        <button type="button" className="ghost" onClick={close}><Icon name="back" size={16} /> {t(workId ? 'tools.back_to_work' : 'tools.back')}</button>
      </div>
      <div className="col" style={{ minHeight: 0, background: 'var(--panel)' }}>
        <nav className="row image-flow" aria-label={t('menu.tools')}>
          {views.map((entry) => (
            <button key={entry.view} type="button" className={view === entry.view ? 'selected' : 'ghost'} aria-current={view === entry.view ? 'page' : undefined} onClick={() => openView(entry.view)}>
              {t(entry.label)}
            </button>
          ))}
        </nav>
        <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
          <div hidden={view !== 'explorer'} inert={view !== 'explorer'} style={{ display: view === 'explorer' ? 'contents' : 'none' }}>
            <TabScope registry={unsaved} tab="explorer">
              <Suspense fallback={<Loading />}>
                <StyleExplorer workId={workId} active={view === 'explorer'} openView={(target) => {
                  if (target === 'queue' || target === 'presets') openView(target);
                }} openSettings={() => openView('settings')} />
              </Suspense>
            </TabScope>
          </div>
          {view === 'queue' && <Suspense fallback={<Loading />}><ImageQueue /></Suspense>}
          {visited.includes('presets') && <div hidden={view !== 'presets'} inert={view !== 'presets'} style={{ display: view === 'presets' ? 'contents' : 'none' }}><TabScope registry={unsaved} tab="presets"><Suspense fallback={<Loading />}><PresetExplorer workId={workId} canOpenGenerate={() => canLeave('presets')} openGenerate={openGenerate} /></Suspense></TabScope></div>}
          {visited.includes('settings') && <div hidden={view !== 'settings'} inert={view !== 'settings'} style={{ display: view === 'settings' ? 'contents' : 'none' }}><TabScope registry={unsaved} tab="settings"><Suspense fallback={<Loading />}><AppSettings request={{ section: 'image', at: 0 }} /></Suspense></TabScope></div>}
        </div>
      </div>
    </div>
  );
}
