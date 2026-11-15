import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { ApiError, get, post, put } from '../../api';
import { t, tm } from '../../i18n';
import { useToast } from '../Toasts';

// Getting models from Civitai (#161): the API key goes into the vault as "civitai" (or civitai-2 …); only the
// reference is kept in the image settings.
export default function DownloadsSection() {
  const qc = useQueryClient();
  const toast = useToast();
  const fail = (err: unknown) => toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
  const settings = useQuery<{ civitai_key: string; nsfw: boolean }>({ queryKey: ['image-settings', 'downloads'], queryFn: () => get('/api/image/settings/downloads') });
  const vault = useQuery<{ name: string }[]>({ queryKey: ['vault'], queryFn: () => get('/api/vault') });
  const [key, setKey] = useState('');
  if (!settings.data) return null;
  const current = settings.data.civitai_key;
  async function save(change: Record<string, unknown>) {
    try {
      await put('/api/image/settings/downloads', change);
      await qc.invalidateQueries({ queryKey: ['image-settings', 'downloads'] });
      qc.invalidateQueries({ queryKey: ['model-downloads'] });
    } catch (err) {
      fail(err);
    }
  }
  async function saveKey() {
    const stored = (vault.data ?? []).map((v) => v.name);
    let name = 'civitai';
    for (let n = 2; stored.includes(name) && current !== `secret:${name}`; n += 1) name = `civitai-${n}`;
    try {
      await post('/api/vault', { name, kind: 'api_key', value: key.trim(), note: 'Civitai' });
      await save({ civitai_key: `secret:${name}` });
      qc.invalidateQueries({ queryKey: ['vault'] });
      setKey('');
      toast({ text: t('common.saved') });
    } catch (err) {
      fail(err);
    }
  }
  return (
    <section className="col">
      <div className="section-title">{t('image_settings.downloads')}</div>
      <p className="faint">{t('image_settings.downloads_note')}</p>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <span className="muted">{t('image_settings.civitai_key')}</span>
        <span className={current ? 'ok-text small' : 'faint small'}>{current ? t('image_settings.civitai_key_set', { name: current.slice('secret:'.length) }) : t('image_settings.civitai_key_none')}</span>
        <input type="password" className="mono" style={{ width: 260 }} value={key} placeholder={t('image_settings.civitai_key_hint')} onChange={(e) => setKey(e.target.value)} />
        <button disabled={!key.trim()} onClick={saveKey}>
          {t('common.save')}
        </button>
        {current && (
          <button className="ghost" onClick={() => save({ civitai_key: '' })}>
            {t('image_settings.civitai_key_clear')}
          </button>
        )}
      </div>
      <label className="row" style={{ gap: 4 }}>
        <input type="checkbox" checked={settings.data.nsfw} onChange={(e) => save({ nsfw: e.target.checked })} />
        {t('image_settings.nsfw_default')}
      </label>
    </section>
  );
}

