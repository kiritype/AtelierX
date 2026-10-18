// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ImageInfoViewer from './ImageInfoViewer';

let host: HTMLDivElement;
let root: Root;
const fetchMock = vi.fn();

beforeEach(async () => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal('fetch', fetchMock);
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:preview');
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  await act(async () => root.render(<ImageInfoViewer active />));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('opens a local file for inspection and displays interpreted and raw values without a workspace request', async () => {
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({
    format: 'PNG', width: 48, height: 32, status: 'parsed',
    generation: { generator: 'novelai', format: 'novelai', evidence: ['Software: NovelAI'], positive: 'blue coat',
      negative: 'blur', settings: { seed: 123, width: 48, height: 32 }, other_nodes: [], notes: [] },
    raw: { text: { Comment: '{"seed":123}' }, exif: {} },
  }) });
  const input = host.querySelector('input[type="file"]') as HTMLInputElement;
  const files = new DataTransfer(); files.items.add(new File(['image'], 'sample.png', { type: 'image/png' }));
  await act(async () => { input.files = files.files; input.dispatchEvent(new Event('change', { bubbles: true })); });
  expect(fetchMock).toHaveBeenCalledOnce();
  expect(fetchMock.mock.calls[0][0]).toBe('/api/image/inspect');
  expect(host.textContent).toContain('blue coat');
  expect(host.textContent).toContain('원본 메타데이터');
  expect(host.textContent).toContain('Comment');
});

it('explains missing metadata after clipboard input and offers the original file action', async () => {
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({
    format: 'PNG', width: 48, height: 32, status: 'none',
    generation: { generator: 'unknown', format: 'unknown', evidence: [], positive: '', negative: '',
      settings: { width: 48, height: 32 }, other_nodes: [], notes: [] },
    raw: { text: {}, exif: {} },
  }) });
  const file = new File(['image'], 'clip.png', { type: 'image/png' });
  const event = new Event('paste', { bubbles: true, cancelable: true });
  Object.defineProperty(event, 'clipboardData', { value: { files: [file], items: [] } });
  await act(async () => { window.dispatchEvent(event); });
  expect(host.textContent).toContain('클립보드로 복사하는 과정');
  expect(host.textContent).toContain('읽을 수 있는 생성 메타데이터가 없습니다');
  expect(host.textContent).toContain('원본 파일 열기');
});
