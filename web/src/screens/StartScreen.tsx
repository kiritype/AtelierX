import { AppMark } from '../components/AppMark';
import type { HelpNavigation } from '../components/Help';
import { Icon } from '../components/icons';
import { MenuButton } from '../components/MenuBar';
import { t } from '../i18n';
import type { GlobalToolsView } from '../lib/imageNavigation';

export default function StartScreen({ help, onOpenWorks, onOpenTools, onLock }: {
  help: HelpNavigation;
  onOpenWorks: () => void;
  onOpenTools: (view: GlobalToolsView) => void;
  onLock: () => void;
}) {
  return (
    <main className="select-page start-screen">
      <header className="row wrap">
        <span className="grow"><AppMark size={28} /></span>
        {help.updateAvailable && (
          <button type="button" className="update-badge" onClick={help.openUpdate} aria-label={t('help.update_badge')} title={t('help.update_badge')}>
            <Icon name="release" size={14} /> <span className="update-badge-label">{t('help.update_badge')}</span>
          </button>
        )}
        <button type="button" className="ghost" onClick={() => onOpenTools('settings')}>
          <Icon name="settings" /> {t('works.app_settings')}
        </button>
        <MenuButton className="ghost" label={t('menu.help')} items={help.entries} />
        <button type="button" className="ghost" onClick={onLock}><Icon name="lock" /> {t('common.lock')}</button>
      </header>
      <h1>{t('start.title')}</h1>
      <div className="start-choices">
        <button type="button" className="start-choice" onClick={onOpenWorks}>
          <Icon name="files" size={24} />
          <span className="col">
            <strong>{t('start.works')}</strong>
            <span className="muted">{t('start.works_detail')}</span>
          </span>
        </button>
        <button type="button" className="start-choice" onClick={() => onOpenTools('single')}>
          <Icon name="image" size={24} />
          <span className="col">
            <strong>{t('start.images')}</strong>
            <span className="muted">{t('start.images_detail')}</span>
          </span>
        </button>
      </div>
    </main>
  );
}
