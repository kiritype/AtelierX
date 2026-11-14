// @vitest-environment happy-dom
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { get, put } from '../../api';
import { t } from '../../i18n';
import type { MossDocument } from '../../imageTypes';
import { compileMoss, freshMoss, templateMoss } from '../../lib/mossLayout';
import MossLayoutEditor from './MossLayoutEditor';

vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), get: vi.fn(), put: vi.fn() }));
let host: HTMLDivElement, root: Root, qc: QueryClient;
let latest: MossDocument;
let change: (doc: MossDocument) => void;
const invalid = vi.fn();
const initial = (): MossDocument => ({ ...freshMoss(), mode: 'layout', scene: 'Cafe #1\nsoft light', items: [
  { id: 'person', label: 'character', name: 'Person', caption: 'sitting', binding: 'manual', rect: [.1, .2, .3, .5] },
  { id: 'sign', label: 'text', name: 'Sign', caption: 'white letters', text: '# 오늘 "영업"\nOPEN', binding: 'manual', rect: [0, 0, 1, .1] },
] });
function Harness() {
  const [value, setValue] = useState(initial); latest = value; change = setValue;
  return <MossLayoutEditor value={value} onChange={setValue} onInvalid={invalid} />;
}
beforeEach(async () => {
  vi.clearAllMocks();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.mocked(get).mockResolvedValue({}); vi.mocked(put).mockResolvedValue({});
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<QueryClientProvider client={qc}><Harness /></QueryClientProvider>));
});
afterEach(async () => { await act(async () => root.unmount()); qc.clear(); host.remove(); });
async function click(text: string) {
  const button = [...host.querySelectorAll('button')].find(b => b.textContent === text)!;
  expect(button).toBeTruthy(); await act(async () => button.click());
}
async function fill(input: HTMLInputElement, value: string) {
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })); });
}
it('encloses fractional coordinates, preserves exact text, and excludes binding metadata', () => {
  const compiled = JSON.parse(compileMoss({ ...latest, width: 1536 }));
  expect(compiled.items[0].bbox).toEqual([-308, -615, 205, -153]);
  expect(compiled.items[1].text).toBe('# 오늘 "영업"\nOPEN');
  expect(compiled.summary.caption).toBe('Cafe #1\nsoft light');
  expect(compiled.items[0]).not.toHaveProperty('id'); expect(compiled.items[0]).not.toHaveProperty('binding');
});
it('rejects invalid numeric input without silently moving the box and restores with undo', async () => {
  const x = host.querySelector('.moss-coordinates input') as HTMLInputElement;
  await fill(x, '-12');
  expect(invalid).toHaveBeenLastCalledWith(true);
  expect(latest.items[0].rect[0]).toBe(.1);
  expect(host.textContent).toContain(t('moss.invalid_rect'));
  await fill(x, '256'); expect(latest.items[0].rect[0]).toBe(.25);
  await click(t('moss.undo')); expect(latest.items[0].rect[0]).toBe(.1);
  await click(t('moss.redo')); expect(latest.items[0].rect[0]).toBe(.25);
});
it('groups a pointer drag into one undo and supports keyboard resize', async () => {
  const canvas = host.querySelector('.moss-canvas') as HTMLDivElement;
  canvas.getBoundingClientRect = () => ({ x: 0, y: 0, left: 0, top: 0, right: 400, bottom: 400, width: 400, height: 400, toJSON: () => ({}) });
  canvas.setPointerCapture = vi.fn();
  const box = host.querySelector('.moss-box') as HTMLButtonElement;
  const pointer = async (el: HTMLElement, type: string, x: number, y: number) => act(async () => { el.dispatchEvent(new PointerEvent(type, { bubbles: true, pointerId: 1, button: 0, clientX: x, clientY: y })); });
  await pointer(box, 'pointerdown', 40, 80);
  await pointer(canvas, 'pointermove', 80, 100);
  await pointer(canvas, 'pointermove', 120, 120);
  await pointer(canvas, 'pointerup', 120, 120);
  expect(latest.items[0].rect[0]).toBeCloseTo(.3);
  await click(t('moss.undo')); expect(latest.items[0].rect).toEqual([.1, .2, .3, .5]);
  await act(async () => box.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'ArrowRight', shiftKey: true })));
  expect(latest.items[0].rect[2]).toBeCloseTo(.3 + 1 / 1024);
});
it('keeps relative boxes when changing aspect ratio and saves reusable templates without specific people', async () => {
  await act(async () => change({ ...latest, width: 1536, height: 768 }));
  expect(latest.items[0].rect).toEqual([.1, .2, .3, .5]);
  expect(host.querySelector<HTMLInputElement>('.moss-coordinates input')?.value).toBe('153.6');
  const doc = initial(); doc.items[0] = { ...doc.items[0], binding: 'target', resolved: { caption: 'person A', name: 'A', negative: '', character_id: 'C001', outfit_id: 'o01', expression_id: 'smile' } };
  expect(templateMoss(doc).items[0].resolved).toBeUndefined(); expect(doc.items[0].resolved?.caption).toBe('person A');
  await fill(host.querySelector('.moss-template-row input')!, 'Cafe');
  await click(t('moss.save_template'));
  expect(put).toHaveBeenCalledWith(expect.stringContaining('/api/image/library/compositions/'), expect.objectContaining({ scope: 'global', revision: null, item: expect.objectContaining({ name: 'Cafe', moss_layout: expect.objectContaining({ width: 1536 }) }) }));
});
