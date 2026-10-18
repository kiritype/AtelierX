import { useEffect, useRef, useState } from 'react';
import { ApiError, notifyUnauthorized } from '../../api';
import { msgText, t } from '../../i18n';
import GenerationInfo, { type Generation } from './GenerationInfo';
import { useToast } from '../Toasts';

type Inspection = {
  format: string;
  width: number;
  height: number;
  status: 'none' | 'partial' | 'parsed';
  metadata_limited?: boolean;
  generation: Generation;
  raw: { text: Record<string, string>; exif: Record<string, string> };
};

const MAX_BYTES = 32 * 1024 * 1024;
const ACCEPT = '.png,.webp,.jpg,.jpeg';

export default function ImageInfoViewer({ active }: { active: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const latest = useRef(0);
  const [preview, setPreview] = useState('');
  const [name, setName] = useState('');
  const [info, setInfo] = useState<Inspection | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState('');
  const [clipboard, setClipboard] = useState(false);
  const [swapped, setSwapped] = useState(false);
  const toast = useToast();

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  const open = async (file: File, fromClipboard = false) => {
    const token = ++latest.current;
    setError('');
    setInfo(null);
    setClipboard(fromClipboard);
    setSwapped(false);
    setName(file.name || t('image_info.clipboard_image'));
    setPreview(URL.createObjectURL(file));
    if (file.size > MAX_BYTES || file.size === 0) {
      setBusy(false);
      setError(t('image_info.size_error'));
      return;
    }
    setBusy(true);
    try {
      const response = await fetch('/api/image/inspect', {
        method: 'POST', body: file, headers: { 'Content-Type': 'application/octet-stream' }, credentials: 'same-origin',
      });
      const result = await response.json();
      if (!response.ok) {
        if (response.status === 401) notifyUnauthorized();
        throw new ApiError(response.status, result?.error ?? { key: 'error.unknown', text: response.statusText });
      }
      if (token === latest.current) setInfo(result as Inspection);
    } catch (err) {
      if (token === latest.current) setError(err instanceof ApiError ? msgText(err.msg) : t('image_info.read_error'));
    } finally {
      if (token === latest.current) setBusy(false);
    }
  };

  useEffect(() => {
    if (!active) return;
    const paste = (event: ClipboardEvent) => {
      const target = event.target;
      if (target instanceof HTMLElement && target.closest('input, textarea, [contenteditable="true"]')) return;
      const file = [...(event.clipboardData?.files ?? [])].find((item) => item.type.startsWith('image/'))
        ?? [...(event.clipboardData?.items ?? [])].find((item) => item.type.startsWith('image/'))?.getAsFile();
      if (file) { event.preventDefault(); void open(file, true); }
    };
    window.addEventListener('paste', paste);
    return () => window.removeEventListener('paste', paste);
  });

  const copy = async (value: string) => {
    try { await navigator.clipboard.writeText(value); toast({ text: t('gallery.copied') }); }
    catch { toast({ text: t('image_info.copy_error'), tone: 'error' }); }
  };
  const rawEntries = info ? [...Object.entries(info.raw.text), ...Object.entries(info.raw.exif).map(([key, value]) => [`EXIF ${key}`, value] as const)] : [];

  return <div className="pad col image-info-viewer">
    <h3>{t('image_menu.info')}</h3>
    <p className="faint">{t('image_info.intro')}</p>
    <div className={`image-info-drop ${dragging ? 'dragging' : ''}`}
      onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => { event.preventDefault(); setDragging(false); const file = event.dataTransfer.files[0]; if (file) void open(file); }}>
      <input ref={input} type="file" accept={ACCEPT} hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void open(file); event.target.value = ''; }} />
      <button onClick={() => input.current?.click()}>{t('image_info.choose')}</button>
      <span className="faint">{t('image_info.drop_paste')}</span>
    </div>
    {clipboard && <p className="warn-text small">{t('image_info.clipboard_warning')} <button className="ghost small" onClick={() => input.current?.click()}>{t('image_info.open_original')}</button></p>}
    {busy && <p className="faint">{t('image_info.reading')}</p>}
    {error && <p role="alert" className="warn-text">{error}</p>}
    {preview && <div className="image-info-content">
      <figure><img src={preview} alt={name} /><figcaption className="faint small">{name}{info && ` · ${info.width} × ${info.height} · ${info.format}`}</figcaption></figure>
      <section className="col">
        {info && <>
          {info.status !== 'parsed' && <p role="status" className="warn-text">{t(`image_info.status.${info.status}`)}</p>}
          {info.status === 'parsed' && info.generation.other_nodes.length > 0 && <p className="faint small">{t('image_info.partial_nodes')}</p>}
          {Object.keys(info.generation.settings).some((key) => key !== 'width' && key !== 'height') &&
            <button className="ghost" onClick={() => void copy(JSON.stringify(info.generation.settings, null, 2))}>{t('image_info.copy_settings')}</button>}
          <GenerationInfo key={name} g={info.generation} swapped={swapped} onSwap={() => setSwapped(!swapped)} />
          <h4>{t('image_info.raw_title')}</h4>
          <p className="faint small">{t('image_info.raw_hint')}</p>
          {info.metadata_limited && <p className="warn-text small">{t('image_info.raw_limited')}</p>}
          {rawEntries.length === 0 ? <p className="faint">{t('image_info.raw_empty')}</p> : rawEntries.map(([key, value]) =>
            <details key={key}>
              <summary>{key}</summary>
              <button className="ghost small" onClick={() => void copy(value)}>{t('image_info.copy_raw')}</button>
              <pre className="image-info-raw">{value}</pre>
            </details>)}
        </>}
      </section>
    </div>}
  </div>;
}
