import { useId, useRef, type KeyboardEvent, type PointerEvent } from 'react';
import { t } from '../../i18n';
import { DEFAULT_SHOT, SHOT_OPTIONS, shotLabel, type Shot } from '../../lib/shots';

const HEIGHTS: Shot['height'][] = ['high', 'eye', 'low'];
const ANGLES = { front: 0, three_quarter: Math.PI / 4, side: Math.PI / 2, back: Math.PI };
const clamp = (n: number, max: number) => Math.max(0, Math.min(max, n));

// This is a diagram of the prompt's discrete choices, not an output prediction.
function Subject({ shot, width, height }: { shot: Shot; width: number; height: number }) {
  const angle = ANGLES[shot.direction];
  const elevation = { high: .42, eye: 0, low: -.3 }[shot.height];
  const focus = { face: 1.65, upper: 1.38, cowboy: 1.26, full: .95 }[shot.framing];
  const scale = height / { face: .56, upper: 1.15, cowboy: 1.4, full: 2.2 }[shot.framing];
  const point = (x: number, y: number, z = 0) => ({
    x: width / 2 + (x * Math.cos(angle) - z * Math.sin(angle)) * scale,
    y: height / 2 - ((y - focus) * Math.cos(elevation) - (x * Math.sin(angle) + z * Math.cos(angle)) * Math.sin(elevation)) * scale,
  });
  const line = (a: number[], b: number[], size: number, key: string) => {
    const p = point(a[0], a[1], a[2]); const q = point(b[0], b[1], b[2]);
    return <line key={key} x1={p.x} y1={p.y} x2={q.x} y2={q.y} strokeWidth={size * scale} strokeLinecap="round" />;
  };
  const torso = [[-.22, 1.45, .11], [.22, 1.45, .11], [.15, .85, .09], [-.15, .85, .09]].map(([x, y, z]) => point(x, y, z));
  const side = [[-.22, 1.45, -.11], [-.22, 1.45, .11], [-.15, .85, .09], [-.15, .85, -.09]].map(([x, y, z]) => point(x, y, z));
  const head = point(0, 1.72); const nose = point(0, 1.71, .19);
  return <g className="shot-subject">
    <g className="shot-limbs">
      {line([-.1, .88, 0], [-.13, .1, .02], .14, 'left-leg')}
      {line([.1, .88, 0], [.13, .1, .02], .14, 'right-leg')}
      {line([-.23, 1.4, 0], [-.32, .88, .03], .11, 'left-arm')}
      {line([.23, 1.4, 0], [.32, .88, .03], .11, 'right-arm')}
      {line([0, 1.44, 0], [0, 1.6, 0], .12, 'neck')}
    </g>
    <polygon points={side.map(p => `${p.x},${p.y}`).join(' ')} strokeWidth={.07 * scale} strokeLinejoin="round" />
    <polygon points={torso.map(p => `${p.x},${p.y}`).join(' ')} strokeWidth={.07 * scale} strokeLinejoin="round" />
    <ellipse cx={head.x} cy={head.y} rx={.15 * scale} ry={.19 * scale} />
    {shot.direction !== 'back' && <g className="shot-face">
      {(shot.direction === 'side' ? [-.055] : [-.055, .055]).map(x => {
        const eye = point(x, 1.75, .14);
        return <circle key={x} cx={eye.x} cy={eye.y} r={.012 * scale} />;
      })}
      <path d={`M ${nose.x + .018 * scale} ${nose.y - .025 * scale} l ${-.025 * scale} ${.055 * scale} h ${.035 * scale}`} fill="none" strokeWidth={.012 * scale} />
    </g>}
  </g>;
}

export function FramePreview({ shot, width, height }: { shot: Shot; width: number; height: number }) {
  const clip = useId();
  const w = Math.min(216, 194 * width / height); const h = w * height / width;
  const x = (240 - w) / 2; const y = (220 - h) / 2;
  return <svg className="shot-preview" viewBox="0 0 240 220" role="img" aria-label={t('shot.camera.preview_label', { shot: shotLabel(shot) })}
    data-framing={shot.framing} data-direction={shot.direction} data-height={shot.height}>
    <defs><clipPath id={clip}><rect width={w} height={h} rx="5" /></clipPath></defs>
    <g transform={`translate(${x} ${y})`}>
      <rect className="shot-frame-bg" width={w} height={h} rx="5" />
      <g clipPath={`url(#${clip})`}>
        <path className="shot-thirds" d={`M ${w / 3} 0 V ${h} M ${w * 2 / 3} 0 V ${h} M 0 ${h / 3} H ${w} M 0 ${h * 2 / 3} H ${w}`} />
        <Subject shot={shot} width={w} height={h} />
      </g>
      <rect className="shot-frame-border" width={w} height={h} rx="5" />
    </g>
  </svg>;
}

export default function ShotCamera({ shot, onChange, outputWidth, outputHeight }: {
  shot: Shot; onChange: (shot: Shot) => void; outputWidth?: number; outputHeight?: number;
}) {
  const hint = useId();
  const drag = useRef<{ id: number; x: number; y: number; width: number; height: number; shot: Shot } | null>(null);
  const knownSize = typeof outputWidth === 'number' && Number.isFinite(outputWidth) && outputWidth > 0
    && typeof outputHeight === 'number' && Number.isFinite(outputHeight) && outputHeight > 0;
  const width = knownSize ? outputWidth : 1024;
  const height = knownSize ? outputHeight : 1024;
  const level = HEIGHTS.indexOf(shot.height);
  const direction = SHOT_OPTIONS.direction.indexOf(shot.direction);
  const frame = SHOT_OPTIONS.framing.indexOf(shot.framing);
  const radius = 70 + frame * 10;
  const camera = (a: number) => ({ x: 146 + Math.sin(a) * radius, y: 130 + Math.cos(a) * radius * .35 + (level - 1) * 40 });
  const selected = camera(ANGLES[shot.direction]);
  const start = (event: PointerEvent<SVGSVGElement>) => {
    if (!event.isPrimary || event.button !== 0) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    event.preventDefault();
    event.currentTarget.focus();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { id: event.pointerId, x: event.clientX, y: event.clientY, width: rect.width, height: rect.height, shot };
  };
  const move = (event: PointerEvent<SVGSVGElement>) => {
    const initial = drag.current;
    if (!initial || initial.id !== event.pointerId) return;
    const d = clamp(SHOT_OPTIONS.direction.indexOf(initial.shot.direction) + Math.round((event.clientX - initial.x) / (initial.width / 4)), 3);
    const h = clamp(HEIGHTS.indexOf(initial.shot.height) + Math.round((event.clientY - initial.y) / (initial.height / 4)), 2);
    onChange({ ...initial.shot, direction: SHOT_OPTIONS.direction[d], height: HEIGHTS[h] });
  };
  const end = (event: PointerEvent<SVGSVGElement>, cancel = false) => {
    const initial = drag.current;
    if (!initial || initial.id !== event.pointerId) return;
    drag.current = null;
    if (cancel) onChange(initial.shot);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  const keyboard = (event: KeyboardEvent<SVGSVGElement>) => {
    const next = { ...shot };
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') next.direction = SHOT_OPTIONS.direction[clamp(direction + (event.key === 'ArrowRight' ? 1 : -1), 3)];
    else if (event.key === 'ArrowUp' || event.key === 'ArrowDown') next.height = HEIGHTS[clamp(level + (event.key === 'ArrowDown' ? 1 : -1), 2)];
    else if (['+', '=', '-'].includes(event.key)) next.framing = SHOT_OPTIONS.framing[clamp(frame + (event.key === '-' ? 1 : -1), 3)];
    else if (event.key === 'Home') Object.assign(next, DEFAULT_SHOT);
    else return;
    event.preventDefault(); onChange(next);
  };
  return <>
    <div className="shot-workspace">
      <section className="shot-camera-panel">
        <div className="shot-panel-title">{t('shot.camera.title')}<span>{t('shot.camera.drag_badge')}</span></div>
        <svg className="shot-orbit" viewBox="0 0 292 220" role="group" tabIndex={0} aria-label={t('shot.camera.control')} aria-describedby={hint}
          data-direction={shot.direction} data-height={shot.height}
          onPointerDown={start} onPointerMove={move} onPointerUp={event => end(event)} onPointerCancel={event => end(event, true)}
          onLostPointerCapture={() => { drag.current = null; }} onKeyDown={keyboard}>
          <path className="shot-floor" d="M 26 149 L 146 109 L 266 149 L 146 193 Z M 66 136 L 186 179 M 106 122 L 226 166 M 66 163 L 186 122 M 106 177 L 226 136" />
          <ellipse className="shot-orbit-guide" cx="146" cy={130 + (level - 1) * 40} rx={radius} ry={radius * .35} />
          <path className="shot-axis-guide" d="M 146 42 V 175" />
          <g className="shot-stage-person">
            <circle cx="146" cy="79" r="13" />
            <path d="M 137 96 Q 146 91 155 96 L 160 126 H 151 L 150 154 H 143 L 141 126 H 132 Z" />
          </g>
          <path className="shot-facing" d="M 146 166 v 16 m -4 -4 l 4 4 4 -4" />
          <text className="shot-orbit-label" x="146" y="208" textAnchor="middle">{t('shot.direction.front')}</text>
          <text className="shot-orbit-label" x="146" y="24" textAnchor="middle">{t('shot.direction.back')}</text>
          {SHOT_OPTIONS.direction.map(value => {
            const p = camera(ANGLES[value]);
            return <circle key={value} className="shot-orbit-stop" cx={p.x} cy={p.y} r="3" />;
          })}
          <path className="shot-sight" d={`M ${selected.x} ${selected.y} L 146 108`} />
          <g className="shot-camera-marker" transform={`translate(${selected.x} ${selected.y})`}>
            <circle r="17" /><rect x="-9" y="-6" width="13" height="12" rx="2" /><path d="M 4 -3 L 10 -6 V 6 L 4 3 Z" />
          </g>
        </svg>
      </section>
      <section className="shot-preview-panel">
        <div className="shot-panel-title">{t('shot.camera.preview')}<span>{t(knownSize ? 'shot.camera.diagram' : 'shot.camera.ratio_unknown')}</span></div>
        <FramePreview shot={shot} width={width} height={height} />
      </section>
    </div>
    <p id={hint} className="shot-camera-hint small">{t('shot.camera.help')}</p>
    <div className="shot-controls">
      {([
        { key: 'direction', label: 'shot.axis.direction', values: SHOT_OPTIONS.direction, value: direction },
        { key: 'height', label: 'shot.axis.height', values: HEIGHTS, value: level },
        { key: 'framing', label: 'shot.camera.distance', values: SHOT_OPTIONS.framing, value: frame },
      ] as const).map(control => <label className="shot-range" key={control.key}>
        <span>{t(control.label)}<strong>{t(`shot.${control.key}.${control.values[control.value]}`)}</strong></span>
        <input type="range" min={0} max={control.values.length - 1} step={1} value={control.value} aria-label={t(control.label)}
          aria-valuetext={t(`shot.${control.key}.${control.values[control.value]}`)}
          onChange={event => onChange({ ...shot, [control.key]: control.values[Number(event.target.value)] })} />
        <span className="shot-range-ends"><span>{t(`shot.${control.key}.${control.values[0]}`)}</span><span>{t(`shot.${control.key}.${control.values[control.values.length - 1]}`)}</span></span>
      </label>)}
    </div>
  </>;
}
