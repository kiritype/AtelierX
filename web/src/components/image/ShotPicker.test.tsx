// @vitest-environment happy-dom
import { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it } from 'vitest';
import { setLanguage, t } from '../../i18n';
import { AUTO_SHOT, compositionSource, shotChoiceFromSource, type ShotChoice, type ShotRules } from '../../lib/shots';
import ShotPicker from './ShotPicker';

const rules: ShotRules = {
  ratings: [],
  slots: [],
  shot_choices: {
    framing: {
      face: { prompt: 'portrait', slots: [] },
      upper: { prompt: 'upper body', slots: ['full', 'hands', 'top'] },
      cowboy: { prompt: 'cowboy shot', slots: ['full', 'hands', 'top', 'bottom'] },
      full: { prompt: 'full body', slots: null },
    },
    direction: { front: 'straight-on', three_quarter: 'three-quarter view', side: 'from side', back: 'from behind' },
    height: { eye: 'eye level', high: 'from above', low: 'from below' },
  },
};

it('shows the direct camera controls, keeps the framing presets in sync, and retains the manual shot across modes', async () => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  function Controlled({ batch }: { batch: boolean }) {
    const [value, setValue] = useState<ShotChoice>(AUTO_SHOT);
    return <ShotPicker batch={batch} value={value} onChange={setValue} rules={rules} />;
  }
  const labels = () => [...host.querySelectorAll('label')];
  const choose = async (text: string) => {
    const input = labels().find(label => label.textContent === text)?.querySelector('input');
    expect(input?.type).toBe('radio');
    await act(async () => input!.click());
    expect(input!.checked).toBe(true);
  };
  try {
    for (const [lang, batch] of [['ko', false], ['en', true]] as const) {
      setLanguage(lang);
      await act(async () => root.render(<Controlled key={lang} batch={batch} />));
      expect(host.textContent).toContain(t(batch ? 'gen.composition_auto' : 'shot.mode.auto'));
      await choose(t('shot.mode.visual'));
      expect(host.querySelector('.shot-orbit')?.getAttribute('role')).toBe('group');
      expect(host.querySelector('.shot-preview-panel > .shot-preview')).not.toBeNull();
      expect(host.querySelector('.shot-applied')?.hasAttribute('open')).toBe(false);
      await choose(t('shot.framing.face'));
      expect(host.querySelector('.shot-preview-panel > .shot-preview')?.getAttribute('data-framing')).toBe('face');
      expect(host.querySelector<HTMLInputElement>(`input[type=range][aria-label="${t('shot.axis.direction')}"]`)?.value).toBe('0');
      expect(host.querySelector<HTMLInputElement>(`input[type=range][aria-label="${t('shot.axis.height')}"]`)?.value).toBe('1');
      const direction = host.querySelector<HTMLInputElement>(`input[type=range][aria-label="${t('shot.axis.direction')}"]`)!;
      const height = host.querySelector<HTMLInputElement>(`input[type=range][aria-label="${t('shot.axis.height')}"]`)!;
      const setRangeValue = (input: HTMLInputElement, value: string) => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value);
        input.dispatchEvent(new Event('input', { bubbles: true }));
      };
      await act(async () => {
        setRangeValue(direction, '2');
        setRangeValue(height, '0');
      });
      expect(host.querySelector('.shot-preview-panel > .shot-preview')?.getAttribute('data-direction')).toBe('side');
      expect(host.querySelector('.shot-preview-panel > .shot-preview')?.getAttribute('data-height')).toBe('high');
      expect(host.textContent).toContain('portrait, from side, from above');
      expect(host.textContent?.includes(t('shot.slots_none'))).toBe(batch);
      await choose(t(batch ? 'gen.composition_auto' : 'shot.mode.auto'));
      expect(host.textContent).not.toContain('portrait, from side, from above');
      await choose(t('shot.mode.visual'));
      expect(host.querySelector('.shot-orbit')?.getAttribute('data-direction')).toBe('side');
      expect(host.querySelector('.shot-orbit')?.getAttribute('data-height')).toBe('high');
      expect(host.querySelector('.shot-preview-panel > .shot-preview')?.getAttribute('data-framing')).toBe('face');
    }
  } finally {
    await act(async () => root.unmount());
    host.remove();
    setLanguage('ko');
  }
});

it('maps pointer drag onto direction and height, synchronizes ranges, and restores the shot on cancel', async () => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  function Controlled() {
    const [value, setValue] = useState<ShotChoice>({ mode: 'visual', shot: { framing: 'upper', direction: 'front', height: 'eye' } });
    return <ShotPicker value={value} onChange={setValue} rules={rules} />;
  }
  const pointer = (node: Element, type: string, values: Record<string, unknown>) => {
    const event = new Event(type, { bubbles: true, cancelable: true });
    for (const [key, value] of Object.entries({ pointerId: 7, isPrimary: true, button: 0, clientX: 100, clientY: 50, ...values })) {
      Object.defineProperty(event, key, { configurable: true, value });
    }
    node.dispatchEvent(event);
  };
  try {
    await act(async () => root.render(<Controlled />));
    const orbit = host.querySelector<SVGSVGElement>('.shot-orbit')!;
    Object.defineProperty(orbit, 'getBoundingClientRect', { value: () => ({ x: 0, y: 0, left: 0, top: 0, right: 200, bottom: 100, width: 200, height: 100, toJSON() {} }) });
    Object.defineProperty(orbit, 'setPointerCapture', { value: () => {} });
    Object.defineProperty(orbit, 'hasPointerCapture', { value: () => true });
    Object.defineProperty(orbit, 'releasePointerCapture', { value: () => {} });
    await act(async () => {
      pointer(orbit, 'pointerdown', {});
      pointer(orbit, 'pointermove', { clientX: 150, clientY: 75 });
    });
    expect(orbit.getAttribute('data-direction')).toBe('three_quarter');
    expect(orbit.getAttribute('data-height')).toBe('low');
    expect(host.querySelector('.shot-preview-panel > .shot-preview')?.getAttribute('data-direction')).toBe('three_quarter');
    expect(host.querySelector('.shot-preview-panel > .shot-preview')?.getAttribute('data-height')).toBe('low');
    expect(host.querySelector<HTMLInputElement>(`input[type=range][aria-label="${t('shot.axis.direction')}"]`)?.value).toBe('1');
    expect(host.querySelector<HTMLInputElement>(`input[type=range][aria-label="${t('shot.axis.height')}"]`)?.value).toBe('2');
    await act(async () => pointer(orbit, 'pointercancel', {}));
    expect(orbit.getAttribute('data-direction')).toBe('front');
    expect(orbit.getAttribute('data-height')).toBe('eye');
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it('supports camera keyboard framing and resets the entire shot with Home', async () => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  function Controlled() {
    const [value, setValue] = useState<ShotChoice>({ mode: 'visual', shot: { framing: 'upper', direction: 'front', height: 'eye' } });
    return <ShotPicker value={value} onChange={setValue} rules={rules} />;
  }
  const key = async (node: Element, value: string) => act(async () => node.dispatchEvent(new KeyboardEvent('keydown', { key: value, bubbles: true })));
  try {
    await act(async () => root.render(<Controlled />));
    const orbit = host.querySelector('.shot-orbit')!;
    await key(orbit, 'ArrowRight');
    await key(orbit, 'ArrowUp');
    await key(orbit, '+');
    expect(orbit.getAttribute('data-direction')).toBe('three_quarter');
    expect(orbit.getAttribute('data-height')).toBe('high');
    expect(host.querySelector('.shot-preview-panel > .shot-preview')?.getAttribute('data-framing')).toBe('face');
    await key(orbit, 'Home');
    expect(orbit.getAttribute('data-direction')).toBe('front');
    expect(orbit.getAttribute('data-height')).toBe('eye');
    expect(host.querySelector('.shot-preview-panel > .shot-preview')?.getAttribute('data-framing')).toBe('upper');
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it('uses an externally restored visual shot as the next manual shot', async () => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  function Controlled() {
    const [value, setValue] = useState<ShotChoice>(AUTO_SHOT);
    return <>
      <button onClick={() => setValue({ mode: 'visual', shot: { framing: 'full', direction: 'back', height: 'low' } })}>Restore shot</button>
      <ShotPicker value={value} onChange={setValue} rules={rules} />
    </>;
  }
  const choose = async (text: string) => {
    const input = [...host.querySelectorAll('label')].find(label => label.textContent === text)?.querySelector('input');
    expect(input).not.toBeNull();
    await act(async () => input!.click());
  };
  try {
    await act(async () => root.render(<Controlled />));
    await act(async () => host.querySelector('button')!.click());
    await choose(t('shot.mode.auto'));
    await choose(t('shot.mode.visual'));
    expect(host.querySelector('.shot-orbit')?.getAttribute('data-direction')).toBe('back');
    expect(host.querySelector('.shot-orbit')?.getAttribute('data-height')).toBe('low');
    expect(host.querySelector('.shot-preview-panel > .shot-preview')?.getAttribute('data-framing')).toBe('full');
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it('remembers the selected library preset while switching through auto', async () => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  const compositions = {
    room: { id: 'room', name: 'Room', prompt: ['quiet room'], negative: [], targets: ['novelai'] },
    garden: { id: 'garden', name: 'Garden', prompt: ['green garden'], negative: [], targets: ['novelai'] },
  };
  function Controlled() {
    const [value, setValue] = useState<ShotChoice>(AUTO_SHOT);
    return <ShotPicker value={value} onChange={setValue} rules={rules} compositions={compositions} target="novelai" />;
  }
  const choose = async (text: string) => {
    const input = [...host.querySelectorAll('label')].find(label => label.textContent === text)?.querySelector('input');
    expect(input).not.toBeNull();
    await act(async () => input!.click());
  };
  try {
    await act(async () => root.render(<Controlled />));
    await choose(t('shot.mode.library'));
    const select = host.querySelector<HTMLSelectElement>('.shot-library select')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!.call(select, 'garden');
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(select.value).toBe('garden');
    await choose(t('shot.mode.auto'));
    await choose(t('shot.mode.library'));
    expect(host.querySelector<HTMLSelectElement>('.shot-library select')?.value).toBe('garden');
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it('uses a known output ratio for the preview frame and labels an unknown ratio when sizes are omitted', async () => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  const value: ShotChoice = { mode: 'visual', shot: { framing: 'upper', direction: 'front', height: 'eye' } };
  const render = async (known: boolean) => act(async () => root.render(
    <ShotPicker value={value} onChange={() => {}} rules={rules} {...(known ? { outputWidth: 1600, outputHeight: 900 } : {})} />,
  ));
  try {
    await render(false);
    expect(host.textContent).toContain(t('shot.camera.ratio_unknown'));
    await render(true);
    expect(host.textContent).toContain(t('shot.camera.diagram'));
    const frame = host.querySelector<SVGRectElement>('.shot-preview-panel > .shot-preview .shot-frame-border')!;
    const width = Number(frame.getAttribute('width'));
    const height = Number(frame.getAttribute('height'));
    expect(width / height).toBeCloseTo(16 / 9, 5);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it('round-trips visual selection ids and honors library targets and notes', () => {
  const id = 'shot:full:three_quarter:low';
  const restored = shotChoiceFromSource(id);
  expect(compositionSource(restored, rules, undefined, 'novelai')).toMatchObject({
    id, positive: 'full body, three-quarter view, from below', negative: '',
  });
  expect(shotChoiceFromSource('shot:full:invalid:low')).toEqual(AUTO_SHOT);
  const library = { bathroom: {
    id: 'bathroom', name: 'Bathroom', prompt: ['warm light # note', 'warm light', '\\#water'],
    negative: ['shadows'], targets: ['anima'], hide_outfit: true,
  } };
  const libraryChoice = shotChoiceFromSource('bathroom');
  expect(compositionSource(libraryChoice, rules, library, 'anima')).toMatchObject({
    id: 'bathroom', name: 'Bathroom', positive: 'warm light, #water', negative: 'shadows',
  });
  expect(compositionSource(libraryChoice, rules, library, 'novelai')).toBeUndefined();
});
