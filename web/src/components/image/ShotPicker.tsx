import { useId } from 'react';
import { t } from '../../i18n';
import { fits } from '../../lib/fragments';
import {
  AUTO_SHOT, DEFAULT_SHOT, SHOT_OPTIONS, compositionSource, shotLabel, shotSlotLabels,
  type Composition, type CompositionSource, type Shot, type ShotChoice, type ShotRules,
} from '../../lib/shots';
import './ShotPicker.css';

const CROP_END: Record<Shot['framing'], number> = { face: 28, upper: 57, cowboy: 78, full: 103 };

function FramingDiagram({ framing }: { framing: Shot['framing'] }) {
  return <svg viewBox="0 0 64 108" aria-hidden="true" className="shot-diagram">
    <g fill="currentColor">
      <circle cx="32" cy="17" r="10" />
      <path d="M28 25h8v7l10 5 8 22-5 2-8-17 2 17-3 39h-6l-2-33-2 33h-6l-3-39 2-17-8 17-5-2 8-22 10-5z" />
    </g>
    <rect x="2" y="3" width="60" height={CROP_END[framing]} rx="4" className="shot-crop" />
  </svg>;
}

function ShotAxis<K extends 'direction' | 'height'>({ axis, options, shot, onChange }: {
  axis: K;
  options: readonly Shot[K][];
  shot: Shot;
  onChange: (value: Shot) => void;
}) {
  const name = useId();
  return <fieldset className="shot-axis">
    <legend>{t(`shot.axis.${axis}`)}</legend>
    <div className="shot-axis-options">
      {options.map(option => <label key={option} className="shot-option">
        <input type="radio" name={name} checked={shot[axis] === option} onChange={() => onChange({ ...shot, [axis]: option })} />
        <span>{t(`shot.${axis}.${option}`)}</span>
      </label>)}
    </div>
  </fieldset>;
}

export function ShotDetails({ positive, negative, slots }: { positive: string; negative: string; slots?: string }) {
  return <dl className="shot-details small">
    <div><dt>{t('shot.positive')}</dt><dd className="mono">{positive || '—'}</dd></div>
    <div><dt>{t('shot.negative')}</dt><dd className="mono">{negative || '—'}</dd></div>
    {slots !== undefined && <div><dt>{t('shot.slots')}</dt><dd>{slots}</dd></div>}
  </dl>;
}

export default function ShotPicker({ batch = false, value, onChange, rules, compositions, target, frozenSource }: {
  batch?: boolean;
  value: ShotChoice;
  onChange: (value: ShotChoice) => void;
  rules?: ShotRules;
  compositions?: Record<string, Composition>;
  target?: string;
  frozenSource?: Pick<CompositionSource, 'name' | 'positive' | 'negative'>;
}) {
  const modeName = useId();
  const framingName = useId();
  const items = Object.values(compositions ?? {});
  const chosen = value.mode === 'library' ? compositions?.[value.id] : undefined;
  const source = frozenSource ?? compositionSource(value, rules, compositions, target);
  const visual = value.mode === 'visual' ? value.shot : undefined;
  const selectMode = (mode: ShotChoice['mode']) => {
    if (mode === 'visual') onChange({ mode, shot: DEFAULT_SHOT });
    else if (mode === 'library') onChange({ mode, id: items.find(item => fits(item, target))?.id ?? '' });
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
        <span>{t(mode === 'auto' && batch ? 'gen.composition_auto' : `shot.mode.${mode}`)}</span>
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
    {visual && <fieldset className="shot-axis">
      <legend>{t('shot.axis.framing')}</legend>
      <div className="shot-frames">
        {SHOT_OPTIONS.framing.map(framing => <label key={framing} className="shot-option">
          <input type="radio" name={framingName} checked={visual.framing === framing}
            onChange={() => onChange({ mode: 'visual', shot: { ...visual, framing } })} />
          <span><FramingDiagram framing={framing} />{t(`shot.framing.${framing}`)}</span>
        </label>)}
      </div>
    </fieldset>}
    {visual && <>
      <ShotAxis axis="direction" options={SHOT_OPTIONS.direction} shot={visual} onChange={shot => onChange({ mode: 'visual', shot })} />
      <ShotAxis axis="height" options={SHOT_OPTIONS.height} shot={visual} onChange={shot => onChange({ mode: 'visual', shot })} />
      <p className="small faint">{t('shot.hint')}</p>
    </>}
    <div className="small" aria-live="polite">{t('shot.summary', { name: visual ? shotLabel(visual) : source?.name ?? chosen?.name
      ?? (value.mode === 'auto' ? t(batch ? 'gen.composition_auto' : 'shot.mode.auto') : t('shot.choose_preset')) })}</div>
    {source && <ShotDetails positive={source.positive} negative={source.negative} slots={slots} />}
    {batch && value.mode === 'auto' && <p className="small faint">{t('shot.auto_hint')}</p>}
  </fieldset>;
}
