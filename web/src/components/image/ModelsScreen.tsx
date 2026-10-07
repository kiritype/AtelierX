import { useState } from 'react';
import { t } from '../../i18n';
import ModelExplorer from './ModelExplorer';
import ModelGet from './ModelGet';
import ModelSearch from './ModelSearch';

// Image menu → Models (#161): my models, searching Civitai, and getting new ones.
type Tab = 'mine' | 'search' | 'get';

export default function ModelsScreen({ openSettings }: { openSettings?: (section?: 'image' | 'install') => void }) {
  const [tab, setTab] = useState<Tab>('mine');
  // A search result handed to the get tab, read there at once.
  const [handed, setHanded] = useState<{ address: string; at: number } | null>(null);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="row pad" style={{ paddingBottom: 0 }}>
        <div className="seg">
          {(['mine', 'search', 'get'] as Tab[]).map((id) => (
            <button key={id} className={tab === id ? 'on' : ''} onClick={() => setTab(id)}>
              {t(`models.tab.${id}`)}
            </button>
          ))}
        </div>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>{tab === 'mine' ? (
          <ModelExplorer />
        ) : tab === 'search' ? (
          <ModelSearch onPick={(address) => (setHanded({ address, at: Date.now() }), setTab('get'))} />
        ) : (
          <ModelGet openSettings={openSettings} handed={handed} />
        )}</div>
    </div>
  );
}
