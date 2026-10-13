import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError, post } from '../../api';
import { t, tm } from '../../i18n';
import type { GalleryToolsResponse, GenerationRecord } from '../../imageTypes';
import { sendToTools } from '../../lib/toolHandoff';
import { useToast } from '../Toasts';

export default function GalleryToolSend({ path, record, openTools }: { path: string; record?: GenerationRecord | null; openTools: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [original, setOriginal] = useState(true);
  let source = record?.postprocessing?.op === 'censor' ? record.postprocessing.source_image
    : record?.op === 'censor' && record.source?.source === 'gallery' ? record.source.path : null;
  // Consecutive censor passes must return to the uncensored source, not an earlier masked result.
  let previous = record?.postprocessing?.previous;
  while (source && previous?.op === 'censor' && previous.source_image) {
    source = previous.source_image;
    previous = previous.previous;
  }
  const censored = !!source || /_censor(?:_\d+)?\.\w+$/i.test(path);
  async function send() {
    setBusy(true);
    try {
      const result = await post<GalleryToolsResponse>('/api/image/tools/gallery', { paths: [original && source ? source : path] });
      const item = result.items[0];
      await qc.invalidateQueries({ queryKey: ['tool-items'] });
      toast({ text: t(result.added.length ? 'gallery.sent_to_tools' : 'gallery.already_in_tools', { n: result.added.length }), action: {
        label: t('image_menu.tools'), run: () => { sendToTools(item.id); openTools(); },
      } });
    } catch (error) {
      toast({ text: error instanceof ApiError ? tm(error.msg) : String(error), tone: 'error' });
    } finally { setBusy(false); }
  }
  return <div className="col">
    {source && <label><input type="checkbox" checked={original} onChange={e => setOriginal(e.target.checked)} /> {t('gallery.send_original')}<div className="faint small" style={{ overflowWrap: 'anywhere' }}>{source}</div></label>}
    {censored && !source && <p className="faint small">{t('gallery.original_unknown')}</p>}
    <button disabled={busy} onClick={send}>{t('gallery.send_to_tools')}</button>
  </div>;
}
