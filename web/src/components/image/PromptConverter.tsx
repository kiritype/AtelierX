import { useEffect, useState } from 'react';
import { t } from '../../i18n';
import { convertPrompts, type Conversion, type Profile } from '../../lib/promptConvert';
import { useToast } from '../Toasts';
import { FAMILY_DEFAULTS } from './GenSettings';
import { sendToLab } from './ImageLab';

export type PromptHandoff = { positive: string; negative: string; settings?: Record<string, any> | null; label?: string };

const PROFILES: Profile[] = ['nai', 'anima', 'sdxl'];
const tp = (key: string, ...values: unknown[]) => t(key, Object.fromEntries(values.map((v, i) => [String(i), v])));

// Image tools → Prompt format: converts weight and artist syntax between NovelAI, Anima and SDXL. Plain text,
// tag order and unknown names are left as they are; what could not be converted is listed.
export default function PromptConverter({ handoff, openLab }: { handoff: PromptHandoff | null; openLab: () => void }) {
  const toast = useToast();
  const [positive, setPositive] = useState('');
  const [negative, setNegative] = useState('');
  const [source, setSource] = useState<Profile>('nai');
  const [target, setTarget] = useState<Profile>('anima');
  const [artists, setArtists] = useState('');
  const [result, setResult] = useState<Conversion | null>(null);
  const [out, setOut] = useState({ positive: '', negative: '' });
  const [origin, setOrigin] = useState<PromptHandoff | null>(null);

  useEffect(() => {
    if (!handoff) return;
    setPositive(handoff.positive);
    setNegative(handoff.negative);
    setOrigin(handoff);
    const family = handoff.settings?.family;
    if (family === 'anima' || family === 'sdxl') setSource(family);
    setResult(null);
  }, [handoff]);

  const run = () => {
    try {
      const converted = convertPrompts({
        positive,
        negative,
        source,
        target,
        artists: artists
          .split(/\r?\n/)
          .map((x) => x.trim())
          .filter(Boolean),
      });
      setResult(converted);
      setOut({ positive: converted.positive, negative: converted.negative });
    } catch (error) {
      toast({ text: `${t('converter.failed')}: ${error instanceof Error ? error.message : error}`, tone: 'error' });
    }
  };
  const copy = async (text: string) => {
    await navigator.clipboard.writeText(text);
    toast({ text: t('gallery.copied') });
  };
  const toLab = () => {
    if (target === 'nai') return;
    // The image's own settings only fit when the family stays the same; otherwise the family defaults.
    const settings = origin?.settings && origin.settings.family === target ? { ...origin.settings, seed: -1 } : { family: target, ...FAMILY_DEFAULTS[target], seed: -1 };
    sendToLab({ positive: out.positive, negative: out.negative, settings, source: null });
    openLab();
  };
  const field = (f: string) => t(`converter.field.${f}`);

  return (
    <div className="col converter">
      <p className="faint">{t('converter.intro')}</p>
      {origin?.label && <div className="faint small">{tp('converter.from', origin.label)}</div>}
      <div className="row" style={{ flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <label className="col" style={{ gap: 2 }}>
          <span className="muted">{t('converter.source')}</span>
          <select value={source} onChange={(e) => (setSource(e.target.value as Profile), setResult(null))}>
            {PROFILES.map((p) => (
              <option key={p} value={p}>
                {t(`converter.profile.${p}`)}
              </option>
            ))}
          </select>
        </label>
        <span>→</span>
        <label className="col" style={{ gap: 2 }}>
          <span className="muted">{t('converter.target')}</span>
          <select value={target} onChange={(e) => (setTarget(e.target.value as Profile), setResult(null))}>
            {PROFILES.map((p) => (
              <option key={p} value={p}>
                {t(`converter.profile.${p}`)}
              </option>
            ))}
          </select>
        </label>
        <button className="primary" onClick={run}>
          {t('converter.convert')}
        </button>
      </div>
      <div className="converter-grid">
        <div className="col">
          <div className="section-title">{t('converter.source_text')}</div>
          <textarea rows={8} className="mono" value={positive} onChange={(e) => (setPositive(e.target.value), setResult(null))} placeholder="positive" />
          <textarea rows={4} className="mono" value={negative} onChange={(e) => (setNegative(e.target.value), setResult(null))} placeholder="negative" />
          <label className="col" style={{ gap: 2 }}>
            <span className="muted">{t('converter.artists')}</span>
            <textarea rows={3} className="mono" value={artists} onChange={(e) => (setArtists(e.target.value), setResult(null))} placeholder={t('converter.artists_placeholder')} />
            <span className="faint small">{t('converter.artists_hint')}</span>
          </label>
        </div>
        <div className="col">
          <div className="section-title">{t('converter.result_text')}</div>
          <textarea rows={8} className="mono" value={out.positive} disabled={!result} onChange={(e) => setOut({ ...out, positive: e.target.value })} />
          <textarea rows={4} className="mono" value={out.negative} disabled={!result} onChange={(e) => setOut({ ...out, negative: e.target.value })} />
          <div className="row" style={{ flexWrap: 'wrap' }}>
            <button disabled={!result} onClick={() => copy(out.positive)}>
              {t('converter.copy_positive')}
            </button>
            <button disabled={!result} onClick={() => copy(out.negative)}>
              {t('converter.copy_negative')}
            </button>
            <button disabled={!result || target === 'nai'} onClick={toLab}>
              {t('gallery.open_in_lab')}
            </button>
          </div>
          {target === 'nai' && <span className="faint small">{t('converter.nai_lab_hint')}</span>}
        </div>
      </div>
      {result && (
        <div className="converter-grid">
          <div className="col">
            <div className="section-title">{t('converter.changes')}</div>
            {result.changes.length === 0 && <span className="faint small">{t('converter.no_changes')}</span>}
            {result.changes.map((c, i) => (
              <div key={i} className="small">
                <span className="faint">{field(c.field)}</span> <span className="mono">{c.before}</span> → <span className="mono">{c.after}</span>
              </div>
            ))}
          </div>
          <div className="col">
            <div className="section-title">{t('converter.warnings')}</div>
            {result.warnings.length === 0 && <span className="faint small">{t('converter.no_warnings')}</span>}
            {result.warnings.map((w, i) => (
              <div key={i} className="small warn-text">
                {tp(`converter.warning.${w.code}`, field(w.field))}
                {w.text && <span className="mono faint"> {w.text}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
