import { useId, useState } from 'react';
import { t } from '../../i18n';
import type { GenerationRecord } from '../../imageTypes';

// The gallery detail request already loaded this record with the app's session.
// Do not open the protected JSON URL in another browser or webview.
export default function GalleryRecord({ record }: { record: GenerationRecord }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return <div className="col" style={{ gap: 6 }}>
    <div className="row">
      <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen(value => !value)}>
        {t(open ? 'gallery.close_record' : 'gallery.open_record')}
      </button>
    </div>
    {open && <textarea id={id} className="mono small" aria-label={t('gallery.record_json')}
      readOnly spellCheck={false} rows={12} wrap="off" value={JSON.stringify(record, null, 2)}
      style={{ width: '100%', minWidth: 0, boxSizing: 'border-box', resize: 'vertical' }} />}
  </div>;
}
