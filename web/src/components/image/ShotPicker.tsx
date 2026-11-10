import { useEffect, useId, useRef } from 'react';
import { t } from '../../i18n';
import { fits } from '../../lib/fragments';
import {
  AUTO_SHOT, DEFAULT_SHOT, SHOT_OPTIONS, compositionSource, shotLabel, shotSlotLabels,
  type Composition, type CompositionSource, type Shot, type ShotChoice, type ShotRules,
} from '../../lib/shots';
import './ShotPicker.css';
import ShotCamera, { FramePreview } from './ShotCamera';

export function ShotDetails({ positive, negative, slots }: { positive: string; negative: string; slots?: string }) {
  return <dl className="shot-details small">
    <div><dt>{t('shot.positive')}</dt><dd className="mono">{positive || '—'}</dd></div>
    <div><dt>{t('shot.negative')}</dt><dd className="mono">{negative || '—'}</dd></div>
    {slots !== undefined && <div><dt>{t('shot.slots')}</dt><dd>{slots}</dd></div>}
  </dl>;
}

export default function ShotPicker({ batch = false, value, onChange, rules, compositions, target, frozenSource, outputWidth, outputHeight }: {
  batch?: boolean;
  value: ShotChoice;
  onChange: (value: ShotChoice) => void;
  rules?: ShotRules;
  compositions?: Record<string, Composition>;
  target?: string;
  frozenSource?: Pick<CompositionSource, 'name' | 'positive' | 'negative'>;
  outputWidth?: number;
  outputHeight?: number;
}) {
  const modeName = useId();
  const framingName = useId();
  const items = Object.values(compositions ?? {});
  const chosen = value.mode === 'library' ? compositions?.[value.id] : undefined;
  const source = frozenSource ?? compositionSource(value, rules, compositions, target);
  const visual = value.mode === 'visual' ? value.shot : undefined;
  const lastShot = useRef<Shot>(DEFAULT_SHOT);
  const lastLibrary = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (value.mode === 'visual') lastShot.current = value.shot;
    if (value.mode === 'library') lastLibrary.current = value.id;
  }, [value]);
  const selectMode = (mode: ShotChoice['mode']) => {
    if (mode === 'visual') onChange({ mode, shot: lastShot.current });
    else if (mode === 'library') onChange({ mode, id: lastLibrary.current ?? items.find(item => fits(item, target))?.id ?? '' });
    else onChange(AUTO_SHOT);
  };
  let slots: string | undefined;
  if (batch && visual && rules?.shot_choices) {
    const shown = rules.shot_choices.framing[visual.framing].slots;
    slots = shown === null ? t('shot.slots_all') : shotSlotLabels(shown, rules) || t('shot.slots_none');
  } else if (batch && source && chosen) {
    slots = chosen.hide_outfit ? t('shot.slots_none')
      : chosen.suggest_slots?.length ? shotSlotLabels([...new Set(['full', ...chosen.suggest_slots])], rules)
      : t('shot.slots_all');
  }
  return <fieldset className="shot-picker">
    <legend>{t('shot.title')}</legend>
    <div className="shot-axis-options">
      {(['auto', 'visual', 'library'] as const).map(mode => <label key={mode} className="shot-option">
        <input type="radio" name={modeName} checked={value.mode === mode} disabled={mode === 'visual' && !rules?.shot_choices}
          onChange={() => selectMode(mode)} />
        <span className="shot-mode-label">
          <span>{t(mode === 'auto' && batch ? 'gen.composition_auto' : `shot.mode.${mode}`)}</span>
          {mode === 'visual' && <span className="shot-beta">{t('shot.beta')}</span>}
        </span>
      </label>)}
    </div>
    {value.mode === 'library' && <label className="shot-library">
      <span>{t('lib.composition')}</span>
      <select value={value.id} onChange={e => onChange({ mode: 'library', id: e.target.value })}>
        <option value="">{t('shot.choose_preset')}</option>
        {value.id && !chosen && <option value={value.id}>{frozenSource?.name ?? value.id}</option>}
        {items.map(item => <option key={item.id} value={item.id}>
          {item.name}{fits(item, target) ? '' : ` (${t('gen.not_applied')})`}
        </option>)}
      </select>
    </label>}
    {value.mode === 'library' && chosen && !source && <span className="warn-text small">{t('gen.not_applied')}</span>}
    {visual && <>
      <div className="shot-editor-heading"><strong>{t('shot.camera.heading')}</strong>
        <button type="button" className="ghost" onClick={() => onChange({ mode: 'visual', shot: DEFAULT_SHOT })}>{t('shot.reset')}</button>
      </div>
      <ShotCamera shot={visual} onChange={shot => onChange({ mode: 'visual', shot })} outputWidth={outputWidth} outputHeight={outputHeight} />
      <fieldset className="shot-axis">
      <legend>{t('shot.axis.framing')}</legend>
      <div className="shot-frames">
        {SHOT_OPTIONS.framing.map(framing => <label key={framing} className="shot-option">
          <input type="radio" name={framingName} checked={visual.framing === framing}
            onChange={() => onChange({ mode: 'visual', shot: { ...visual, framing } })} />
          <span><span className="shot-preset-diagram" aria-hidden="true"><FramePreview shot={{ ...DEFAULT_SHOT, framing }} width={3} height={4} /></span>{t(`shot.framing.${framing}`)}</span>
        </label>)}
      </div>
      </fieldset>
      <p className="small faint">{t('shot.hint')}</p>
    </>}
    <div className="shot-summary small" aria-live="polite">{t('shot.summary', { name: visual ? shotLabel(visual) : source?.name ?? chosen?.name
      ?? (value.mode === 'auto' ? t(batch ? 'gen.composition_auto' : 'shot.mode.auto') : t('shot.choose_preset')) })}</div>
    {source && <details className="shot-applied"><summary>{t('shot.applied')}</summary><ShotDetails positive={source.positive} negative={source.negative} slots={slots} /></details>}
    {batch && value.mode === 'auto' && <p className="small faint">{t('shot.auto_hint')}</p>}
  </fieldset>;
}
