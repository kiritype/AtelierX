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

it('keeps each radio group independent and shows the exact selected shot text in both modes', async () => {
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
      const cropHeights = [...host.querySelectorAll('.shot-crop')].map(rect => Number(rect.getAttribute('height')));
      expect(cropHeights).toHaveLength(4);
      expect(cropHeights).toEqual([...new Set(cropHeights)].sort((a, b) => a - b));
      await choose(t('shot.framing.face'));
      await choose(t('shot.direction.side'));
      await choose(t('shot.height.high'));
      expect([...host.querySelectorAll<HTMLInputElement>('input:checked')].map(input => input.parentElement?.textContent)).toEqual(
        ['shot.mode.visual', 'shot.framing.face', 'shot.direction.side', 'shot.height.high'].map(key => t(key)),
      );
      expect(host.textContent).toContain('portrait, from side, from above');
      expect(host.textContent?.includes(t('shot.slots_none'))).toBe(batch);
      await choose(t(batch ? 'gen.composition_auto' : 'shot.mode.auto'));
      expect(host.textContent).not.toContain('portrait, from side, from above');
    }
  } finally {
    await act(async () => root.unmount());
    host.remove();
    setLanguage('ko');
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
