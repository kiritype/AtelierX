import { useState } from 'react';
import { ApiError, post } from '../../api';
import { msgText, t, tm } from '../../i18n';
import { PRESET_ID } from '../../lib/presetFromRecord';
import { useToast } from '../Toasts';
import { Dialog } from '../ui';
import { presetTarget } from './PresetEditor';

// Bringing in a style preset package (#169): each preset is shown first, with the files this PC lacks, and the person
// chooses per preset. Nothing is written until "Bring in".
type Missing = { kind: string; name: string; sha256?: string; civitai?: string };
type Item = { id: string; name: string; service: string; family: string; exists: boolean; preview: boolean; missing: Missing[] };
export type ImportLook = { token: string; app_version?: string; checked: boolean; items: Item[] };
type Choice = 'add' | 'replace' | 'skip' | 'rename';

export async function readPackage(file: File): Promise<ImportLook> {
  const response = await fetch('/api/image/presets/import/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/zip' },
    body: file,
    credentials: 'same-origin',
  });
  const data = await response.json();
  if (!response.ok) throw new Error(msgText(data.error) || t('presets.share.bad'));
  return data;
}

export default function PresetImport({ look, onClose, onDone }: { look: ImportLook; onClose: () => void; onDone: (written: string[], presets: unknown) => void }) {
  const toast = useToast();
  const [choices, setChoices] = useState<Record<string, Choice>>(() => Object.fromEntries(look.items.map((i) => [i.id, i.exists ? 'skip' : 'add'])));
  const [names, setNames] = useState<Record<string, string>>(() => Object.fromEntries(look.items.map((i) => [i.id, `${i.id}_shared`])));
  const [busy, setBusy] = useState(false);
  const bad = look.items.some((i) => choices[i.id] === 'rename' && !PRESET_ID.test(names[i.id] ?? ''));
  const count = look.items.filter((i) => choices[i.id] !== 'skip').length;

  async function apply() {
    setBusy(true);
    try {
      const body = Object.fromEntries(look.items.map((i) => [i.id, choices[i.id] === 'rename' ? { as: names[i.id] } : choices[i.id]]));
      const done = await post<{ written: string[]; presets: unknown }>('/api/image/presets/import', { token: look.token, choices: body });
      onDone(done.written, done.presets);
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      title={t('presets.share.import_title')}
      onClose={onClose}
      className="wide"
      actions={
        <button className="primary" disabled={busy || bad || !count} onClick={apply}>
          {t('presets.share.import_apply', { n: count })}
        </button>
      }
    >
      <p className="faint small">{look.checked ? t('presets.share.import_about') : t('presets.share.import_unchecked')}</p>
      <div className="col" style={{ gap: 10, maxHeight: '60vh', overflow: 'auto' }}>
        {look.items.map((item) => (
          <div key={item.id} className="col gen-patch" style={{ gap: 4 }}>
            <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
              <strong>{item.name}</strong>
              <span className="faint mono small">{item.id}</span>
              <span className="chip small">{presetTarget(item)}</span>
              {item.preview && <span className="chip small faint">{t('presets.share.has_preview')}</span>}
              {item.exists && <span className="chip small warn">{t('presets.share.exists')}</span>}
              <span className="grow" />
              <select value={choices[item.id]} onChange={(e) => setChoices({ ...choices, [item.id]: e.target.value as Choice })}>
                {item.exists ? (
                  <>
                    <option value="skip">{t('presets.share.choice.skip')}</option>
                    <option value="replace">{t('presets.share.choice.replace')}</option>
                    <option value="rename">{t('presets.share.choice.rename')}</option>
                  </>
                ) : (
                  <>
                    <option value="add">{t('presets.share.choice.add')}</option>
                    <option value="skip">{t('presets.share.choice.skip')}</option>
                  </>
                )}
              </select>
              {choices[item.id] === 'rename' && (
                <input className="mono" style={{ width: 160 }} value={names[item.id]} onChange={(e) => setNames({ ...names, [item.id]: e.target.value })} aria-label={t('presets.share.new_id')} />
              )}
            </div>
            {item.missing.length > 0 && (
              <div className="col small" style={{ gap: 2 }}>
                <span className="warn-text">{t('presets.share.missing', { n: item.missing.length })}</span>
                {item.missing.map((m, i) => (
                  <span key={i} className="mono faint">
                    {t(`presets.share.kind.${m.kind}`)} · {m.name}
                    {m.civitai ? ` · ${m.civitai}` : ''}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </Dialog>
  );
}
