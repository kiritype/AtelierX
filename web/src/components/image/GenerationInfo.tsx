import { useState } from 'react';
import { t } from '../../i18n';
import { useToast } from '../Toasts';

// The generation table of an image (#169): which tool made it (with the evidence, and the person may correct it),
// the settings read from the file by rules, and whether this PC has the files. Viewing only: nothing is sent.
type Named = { name: string; hash?: string; version?: string; version_id?: string; title?: string; strength?: number; found?: string | null; by?: string | null; similar?: string | null };
export type Generation = {
  generator: string;
  format: string;
  evidence: string[];
  positive: string;
  negative: string;
  settings: Record<string, any> & { model?: Named; text_encoder?: Named; loras?: Named[]; upscale?: Record<string, any> };
  other_nodes: string[];
  notes: { kind: 'sampler' | 'scheduler'; name: string; nearest: string }[];
};
const GENERATORS = ['comfyui', 'webui', 'novelai', 'pixai', 'atelierx', 'unknown'];
const tp = (key: string, ...values: unknown[]) => t(key, Object.fromEntries(values.map((v, i) => [String(i), v])));
const base = (name?: string | null) => (name ?? '').replace(/^checkpoint::/, '').split(/[\\/]/).pop() ?? '';

function Presence({ item }: { item: Named }) {
  if (item.found) return <span className="ok-text small">{tp('gen_info.have', t(`gen_info.by.${item.by}`))}</span>;
  if (item.similar) return <span className="warn-text small">{tp('gen_info.similar', base(item.similar))}</span>;
  return <span className="faint small">{t('gen_info.missing')}</span>;
}

export default function GenerationInfo({ g, swapped, onSwap }: { g: Generation; swapped: boolean; onSwap: () => void }) {
  const toast = useToast();
  const [generator, setGenerator] = useState(g.generator);
  const s = g.settings;
  const copy = async (text: string) => {
    await navigator.clipboard.writeText(text);
    toast({ text: t('gallery.copied') });
  };
  const positive = swapped ? g.negative : g.positive;
  const negative = swapped ? g.positive : g.negative;
  const row = (label: string, value: unknown, extra?: React.ReactNode) =>
    value === undefined || value === null || value === '' ? null : (
      <tr key={label}>
        <th>{label}</th>
        <td className="mono" onClick={() => copy(String(value))} title={t('gallery.click_copy')}>
          {String(value)}
        </td>
        <td>{extra}</td>
      </tr>
    );
  const noteFor = (kind: string) => g.notes.find((n) => n.kind === kind);
  return (
    <div className="col gen-info" style={{ gap: 6 }}>
      <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
        <span className="muted small">{t('gen_info.made_with')}</span>
        <select value={generator} onChange={(e) => setGenerator(e.target.value)} title={t('gen_info.correct_hint')}>
          {GENERATORS.map((id) => (
            <option key={id} value={id}>
              {t(`gen_info.generator.${id}`)}
            </option>
          ))}
        </select>
        {generator !== g.generator && <span className="faint small">{tp('gen_info.read_as', t(`gen_info.generator.${g.generator}`))}</span>}
        <span className="faint small">{g.evidence.length ? g.evidence.join(' · ') : t('gen_info.no_evidence')}</span>
      </div>
      {(positive || negative) && (
        <>
          <div className="row">
            <span className="muted small grow">{t('gen_info.prompts')}</span>
            <button className="ghost small" onClick={onSwap} title={t('gen_info.swap_hint')}>
              {t('gen_info.swap')}
            </button>
          </div>
          {positive && (
            <div className="prompt-box mono small" onClick={() => copy(positive)} title={t('gallery.click_copy')}>
              {positive}
            </div>
          )}
          {negative && (
            <div className="prompt-box mono small faint" onClick={() => copy(negative)} title={t('gallery.click_copy')}>
              − {negative}
            </div>
          )}
        </>
      )}
      <table className="gen-table small">
        <tbody>
          {s.model && row(t('gen.model'), s.model.title ? `${s.model.name} (${s.model.title})` : s.model.name, <Presence item={s.model} />)}
          {s.model?.hash && row(t('gen_info.hash'), s.model.hash)}
          {s.text_encoder && row(t('gen.text_encoder'), s.text_encoder.name, <Presence item={s.text_encoder} />)}
          {(s.loras ?? []).map((l, i) => (
            <tr key={`lora-${i}`}>
              <th>{i === 0 ? t('gen.loras') : ''}</th>
              <td className="mono" onClick={() => copy(l.name)} title={t('gallery.click_copy')}>
                {l.name}
                {l.version ? ` ${l.version}` : ''} · {l.strength ?? 1}
              </td>
              <td>
                <Presence item={l} />
              </td>
            </tr>
          ))}
          {row(t('gen.sampler'), s.sampler, noteFor('sampler') && <span className="warn-text small">{tp('gen_info.not_here', noteFor('sampler')!.nearest)}</span>)}
          {row(t('gen.scheduler'), s.scheduler, noteFor('scheduler') && <span className="warn-text small">{tp('gen_info.not_here', noteFor('scheduler')!.nearest)}</span>)}
          {row(t('gen.steps'), s.steps)}
          {row('CFG', s.cfg ?? s.scale)}
          {row('shift', s.shift)}
          {row(t('gen.seed'), s.seed)}
          {row(t('gallery.size'), s.width && s.height ? `${s.width} × ${s.height}` : undefined)}
          {row('noise schedule', s.noise_schedule)}
          {s.upscale &&
            row(
              t('gen.upscale'),
              [s.upscale.model, s.upscale.scale && `×${s.upscale.scale}`, s.upscale.steps && `${s.upscale.steps} steps`, s.upscale.denoise && `denoise ${s.upscale.denoise}`].filter(Boolean).join(' · '),
              s.upscale.model && (s.upscale.model_found ? <span className="ok-text small">{t('gen_info.have_short')}</span> : <span className="faint small">{t('gen_info.missing')}</span>),
            )}
        </tbody>
      </table>
      {g.other_nodes.length > 0 && (
        <details>
          <summary className="small">{tp('gen_info.other_nodes', String(g.other_nodes.length))}</summary>
          <p className="faint small">{t('gen_info.other_nodes_hint')}</p>
          <div className="mono small">{g.other_nodes.join(', ')}</div>
        </details>
      )}
    </div>
  );
}
