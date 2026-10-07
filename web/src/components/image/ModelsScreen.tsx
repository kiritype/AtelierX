import { useState } from 'react';
import { t } from '../../i18n';
import ModelExplorer from './ModelExplorer';
import ModelGet from './ModelGet';

// Image menu → Models (#161): my models, and getting new ones.
type Tab = 'mine' | 'get';

export default function ModelsScreen({ openSettings }: { openSettings?: (section?: 'image' | 'install') => void }) {
  const [tab, setTab] = useState<Tab>('mine');
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="row pad" style={{ paddingBottom: 0 }}>
        <div className="seg">
          {(['mine', 'get'] as Tab[]).map((id) => (
            <button key={id} className={tab === id ? 'on' : ''} onClick={() => setTab(id)}>
              {t(`models.tab.${id}`)}
            </button>
          ))}
        </div>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>{tab === 'mine' ? <ModelExplorer /> : <ModelGet openSettings={openSettings} />}</div>
    </div>
  );
}
