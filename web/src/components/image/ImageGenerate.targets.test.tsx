// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { get, post } from '../../api';
import { t } from '../../i18n';
import { PRESET_HANDOFF } from '../../lib/presetHandoff';
import ImageGenerate, { sendToGenerate } from './ImageGenerate';
import { COMFY_PREVIEW_CATALOG, NOVELAI_PREVIEW_INFO, PIXAI_PREVIEW_INFO } from './singlePreviewSettings';

vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), get: vi.fn(), post: vi.fn() }));

const expressions = {
  shared: { id: 'shared', name: 'Shared smile', rating: 'general', targets: [] },
  anima: { id: 'anima', name: 'Anima smile', rating: 'general', targets: ['anima'] },
  sdxl: { id: 'sdxl', name: 'SDXL smile', rating: 'general', targets: ['sdxl'] },
  moss: { id: 'moss', name: 'MOSS smile', rating: 'general', targets: ['moss'] },
  nai: { id: 'nai', name: 'NAI smile', rating: 'general', targets: ['novelai'] },
  pixai: { id: 'pixai', name: 'PixAI smile', rating: 'general', targets: ['pixai'] },
  naiExtra: { id: 'naiExtra', name: 'NAI extra', rating: 'nai-only', targets: ['novelai'] },
};
const target = (expression_id: string) => ({ character_id: 'c1', outfit_id: 'o1', expression_id });
let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;

beforeEach(() => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  sessionStorage.clear();
  vi.clearAllMocks();
  vi.stubGlobal('confirm', vi.fn(() => true));
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  qc.setQueryData(['image-designs', 'work'], [{ id: 'c1', name: 'Character', path: 'c1.md', has_design: true, outfits: [{ id: 'o1', name: 'Suit' }] }]);
  qc.setQueryData(['image-lib', 'expressions', 'work'], expressions);
  qc.setQueryData(['image-lib', 'common', 'work'], {});
  qc.setQueryData(['image-lib', 'compositions', 'work'], {});
  qc.setQueryData(['image-lib-rules'], { ratings: [{ id: 'general', name: 'General' }, { id: 'nai-only', name: 'NAI group' }], slots: [] });
  qc.setQueryData(['image-presets'], [{ id: 'nai-preset', name: 'NAI style', service: 'novelai', family: 'novelai', tags: [], settings: {}, common: [], artist: { positive: '', negative: '' } }]);
  qc.setQueryData(['review-settings'], { enabled: false });
  qc.setQueryData(['image-services'], { services: ['novelai', 'pixai'].map(id => ({ id, name: id === 'novelai' ? 'NovelAI' : 'PixAI', supported: true, connected: true })) });
  qc.setQueryData(['image-catalog'], COMFY_PREVIEW_CATALOG);
  qc.setQueryData(['image-service-info', 'novelai'], NOVELAI_PREVIEW_INFO);
  qc.setQueryData(['image-service-account', 'novelai'], { active: false, opus: false });
  qc.setQueryData(['image-service-info', 'pixai'], PIXAI_PREVIEW_INFO);
  vi.mocked(get).mockRejectedValue(new Error('Unexpected uncached request'));
  vi.mocked(post).mockImplementation(async (url, body) => url.endsWith('/compose') ? [] : { count: (body as { targets: unknown[] }).targets.length });
});

afterEach(async () => {
  await act(async () => root.unmount());
  qc.clear();
  host.remove();
  localStorage.clear();
  sessionStorage.clear();
  vi.unstubAllGlobals();
});

async function render() {
  await act(async () => root.render(<QueryClientProvider client={qc}><ImageGenerate workId="work" openQueue={() => {}} openItem={() => {}} /></QueryClientProvider>));
}
const button = (name: string) => [...host.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent === name)!;
async function click(element: HTMLElement) {
  expect(element).toBeTruthy();
  await act(async () => element.click());
}
const shown = () => [...host.querySelectorAll('.image-gen-pick label')].filter(label => label.querySelector('input[type="checkbox"]')).map(label => label.textContent);
const box = (label: string) => [...host.querySelectorAll('label')].find(el => el.textContent === label)!.querySelector<HTMLInputElement>('input')!;
function expectTotal(n: number) {
  expect(host.querySelector('footer')!.textContent).toContain(t('gen.bar_total', { targets: n, count: 1, n }));
}
async function expectRequest(expressionIds: string[], action = 'gen.preview') {
  await click(button(t(action)));
  const request = vi.mocked(post).mock.lastCall?.[1] as { targets: ReturnType<typeof target>[] };
  expect(request.targets).toEqual(expressionIds.map(target));
}

it('filters expressions and select-all by service, retaining shared and previous selections', async () => {
  await render();
  expect(shown()).toEqual(['General', 'Shared smile', 'Anima smile']);
  await click(host.querySelector<HTMLInputElement>(`input[aria-label="${t('gen.table.all')}"]`)!);
  await click(box('General'));
  expectTotal(2);
  await expectRequest(['shared', 'anima'], 'gen.enqueue');

  await click(button('NovelAI'));
  expect(shown()).toEqual(['General', 'Shared smile', 'NAI smile', 'NAI group', 'NAI extra']);
  expectTotal(1);
  await click(box('General'));
  expectTotal(2);
  await expectRequest(['shared', 'nai']);

  await click(button('PixAI'));
  expect(shown()).toEqual(['General', 'Shared smile', 'PixAI smile']);
  expectTotal(1);
  await expectRequest(['shared'], 'gen.enqueue');

  await click(button('ComfyUI'));
  expect(box('Anima smile').checked).toBe(true);
  expectTotal(2);
  await expectRequest(['shared', 'anima']);
});

it('updates expression visibility and requests when the ComfyUI model family changes', async () => {
  await render();
  await click(host.querySelector<HTMLInputElement>(`input[aria-label="${t('gen.table.all')}"]`)!);
  await click(box('Anima smile'));
  await click(button('SDXL·IL'));
  expect(shown()).toEqual(['General', 'Shared smile', 'SDXL smile']);
  expectTotal(0);
  expect(button(t('gen.preview')).disabled).toBe(true);
  expect(button(t('gen.enqueue')).disabled).toBe(true);
  await click(box('SDXL smile'));
  await expectRequest(['sdxl']);
  await click(button('MOSS Beta'));
  expect(shown()).toEqual(['General', 'Shared smile', 'MOSS smile']);
  expectTotal(0);
  await click(box('MOSS smile'));
  await expectRequest(['moss']);
});

it('filters board combinations after library loading and after a preset changes the service', async () => {
  qc.removeQueries({ queryKey: ['image-lib', 'expressions', 'work'] });
  let resolveExpressions!: (value: typeof expressions) => void;
  vi.mocked(get).mockImplementation(() => new Promise(resolve => { resolveExpressions = resolve; }));
  sendToGenerate(['shared', 'nai', 'missing'].map(target));
  await render();
  expectTotal(0);
  expect(button(t('gen.enqueue')).disabled).toBe(true);
  await act(async () => { resolveExpressions(expressions); });
  await vi.waitFor(() => expect(button(t('gen.preview')).disabled).toBe(false));
  expect(host.querySelector('.handed-targets')!.textContent).toContain(t('gen.handed', { n: 1 }));
  expect(host.querySelector('.handed-targets')!.textContent).toContain(t('gen.handed_expressions_excluded', { n: 2 }));
  await expectRequest(['shared']);

  await act(async () => window.dispatchEvent(new CustomEvent(PRESET_HANDOFF, { detail: 'nai-preset' })));
  expect(host.querySelector('.handed-targets')!.textContent).toContain(t('gen.handed', { n: 2 }));
  expectTotal(2);
  await expectRequest(['shared', 'nai'], 'gen.enqueue');
});

it('rechecks selected expressions when their library targets change', async () => {
  await render();
  await click(host.querySelector<HTMLInputElement>(`input[aria-label="${t('gen.table.all')}"]`)!);
  await click(box('General'));
  await act(async () => {
    qc.setQueryData(['image-lib', 'expressions', 'work'], { ...expressions, anima: { ...expressions.anima, targets: ['novelai'] } });
  });
  await vi.waitFor(() => expect(shown()).not.toContain('Anima smile'));
  expectTotal(1);
  await expectRequest(['shared'], 'gen.enqueue');
});
