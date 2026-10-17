// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import GalleryRecord from './GalleryRecord';
import type { GenerationRecord } from '../../imageTypes';

let host: HTMLDivElement, root: Root;
const record: GenerationRecord = { positive: '한글 "prompt" <script>alert(1)</script>', negative: 'blur',
  seed: 123, settings: { seed: 123, steps: 20, loras: [{ name: 'test', strength: 0.7 }] } };
async function render(key: string, value = record) {
  await act(async () => root.render(<GalleryRecord key={key} record={value} />));
}
async function toggle() { await act(async () => host.querySelector('button')!.click()); }
beforeEach(() => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); });
it('opens the authenticated record inline without navigation or another request', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch'); const open = vi.spyOn(window, 'open');
  await render('first'); expect(host.querySelector('textarea')).toBeNull();
  await toggle();
  const area = host.querySelector('textarea')!;
  expect(area.readOnly).toBe(true);
  expect(JSON.parse(area.value)).toEqual(record);
  expect(host.querySelector('script')).toBeNull();
  expect(host.querySelector('a')).toBeNull();
  expect(fetch).not.toHaveBeenCalled(); expect(open).not.toHaveBeenCalled();
  expect(host.querySelector('button')!.getAttribute('aria-expanded')).toBe('true');
  expect(host.querySelector('button')!.getAttribute('aria-controls')).toBe(area.id);
  area.focus(); area.select(); expect(area.selectionEnd).toBe(area.value.length);
  await toggle(); expect(host.querySelector('textarea')).toBeNull();
});
it('closes and discards the previous image record when the image changes', async () => {
  await render('first'); await toggle();
  await render('second', { positive: 'second', seed: 456 });
  expect(host.querySelector('textarea')).toBeNull();
  await toggle(); expect(JSON.parse(host.querySelector('textarea')!.value)).toEqual({ positive: 'second', seed: 456 });
});
