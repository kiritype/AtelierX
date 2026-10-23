// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { get, post } from '../../api';
import { t } from '../../i18n';
import ImageExperiments, { PoolEditor, StyleExplorer } from './StyleExplorer';
import type { PoolItem } from '../../imageTypes';
vi.mock('../../api', async (original) => ({ ...(await original<typeof import('../../api')>()), get: vi.fn(), post: vi.fn() }));
vi.mock('./ImageLab', () => ({ default: () => null, HANDOFF_KEY: 'atelierx-lab-handoff', hasLabHandoff: () => false }));
vi.mock('./GenSettings', () => ({ default: () => null, useCatalog: () => ({ data: { models: ['m'], loras: [] } }) }));
vi.mock('./NovelAISettings', () => ({ default: () => null }));
vi.mock('../Unsaved', () => ({ useUnsaved: vi.fn() }));
let host: HTMLDivElement, root: Root, qc: QueryClient;
beforeEach(() => {
  vi.clearAllMocks();
  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  HTMLDialogElement.prototype.showModal = vi.fn();
  vi.mocked(get).mockImplementation(async (url) =>
    url.includes('/artists')
      ? { available: true, total: 80, items: url.includes('offset=50') ? ['second'] : ['first'] }
      : url.includes('/pools')
        ? { revision: 'r', items: [] }
        : [],
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  qc.clear();
  host.remove();
  vi.unstubAllGlobals();
});
async function render(child: React.ReactNode) {
  await act(async () => {
    root.render(<QueryClientProvider client={qc}>{child}</QueryClientProvider>);
    await new Promise((r) => setTimeout(r, 0));
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 10));
  });
}
const button = (text: string) => [...host.querySelectorAll('button')].find((x) => x.textContent === text)!;
it('votes by image or number while ignoring typing, repeats and inactive screens', async () => {
  const candidates = ['left', 'right'].map(id => ({id, status: 'done', config: {}, image_url: `/${id}.png`, attempts: []}));
  const doc = {id: 'session', revision: 'r', name: 'demo', service: 'comfyui', family: 'anima', pools: {artists: [], models: [], loras: []}, rules: {}, settings: {}, candidates, events: [], scores: Object.fromEntries(candidates.map(c => [c.id, {score: 1000, count: 0, bad: 0}])), pair: ['left', 'right']};
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}')));
  vi.mocked(get).mockImplementation(async url => url.endsWith('/sessions/session') ? doc : url.endsWith('/sessions') ? [doc] : {revision: 'r', items: []});
  vi.mocked(post).mockResolvedValue(doc);
  await render(<StyleExplorer openPresets={vi.fn()} />);
  await act(async () => {
    const select = [...host.querySelectorAll('select')].find(el => [...el.options].some(o => o.value === 'session'))!;
    select.value = 'session';
    select.dispatchEvent(new Event('change', {bubbles: true}));
    await new Promise(r => setTimeout(r, 20));
  });
  await render(<StyleExplorer openPresets={vi.fn()} />);
  await act(async () => { host.querySelector<HTMLImageElement>('img[alt="A"]')!.click(); });
  expect(post).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({action: 'evaluate', choice: 'a'}));
  for (const [index, choice] of ['a', 'b', 'tie', 'bad', 'skip'].entries()) {
    await act(async () => { window.dispatchEvent(new KeyboardEvent('keydown', {key: String(index + 1)})); });
    expect(post).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({choice}));
  }
  vi.mocked(post).mockClear();
  await act(async () => {
    host.querySelector('input')!.dispatchEvent(new KeyboardEvent('keydown', {key: '1', bubbles: true}));
    window.dispatchEvent(new KeyboardEvent('keydown', {key: '2', repeat: true}));
    window.dispatchEvent(new KeyboardEvent('keydown', {key: '3', ctrlKey: true}));
  });
  await render(<StyleExplorer openPresets={vi.fn()} active={false} />);
  await act(async () => { window.dispatchEvent(new KeyboardEvent('keydown', {key: '1'})); });
  expect(post).not.toHaveBeenCalled();
});
async function click(text: string) {
  await act(async () => {
    button(text).click();
    await new Promise((r) => setTimeout(r, 10));
  });
}
it('keeps artist choices across pages and applies an independent copy without saving the global pool', async () => {
  const apply = vi.fn<(x: PoolItem[]) => void>();
  await render(
    <PoolEditor
      kind="artists"
      initial={[]}
      document={{ revision: 'r', items: [] }}
      catalogNames={[]}
      onDocument={vi.fn()}
      onApply={apply}
      onClose={vi.fn()}
    />,
  );
  await act(async () => {
    (host.querySelector('input[type=checkbox]') as HTMLInputElement).click();
  });
  await click(t('explore.next'));
  expect(host.textContent).toContain('second');
  expect(host.textContent).toContain('first');
  await act(async () => {
    ([...host.querySelectorAll('input[type=checkbox]')][0] as HTMLInputElement).click();
  });
  await click(t('explore.use_pool'));
  expect(apply.mock.calls[0][0].map((x) => x.name)).toEqual(['first', 'second']);
  expect(post).not.toHaveBeenCalled();
});
it('starts with comparison and search settings collapsed and never generates automatically', async () => {
  await render(<StyleExplorer openPresets={vi.fn()} />);
  const conditions = [...host.querySelectorAll('details')].filter(x => x.querySelector('summary')?.textContent?.startsWith(t('explore.conditions')) || x.querySelector('summary')?.textContent === t('explore.rules'));
  expect(conditions).toHaveLength(2);
  expect(conditions.every(x => !x.open)).toBe(true);
  expect(host.textContent).toContain(t('explore.artists'));
  expect(host.textContent).toContain(t('explore.models'));
  expect(host.textContent).toContain(t('explore.loras'));
  expect(post).not.toHaveBeenCalled();
});

it('keeps the checkbox inside its whole-row label and wraps the tag separately', async () => {
  await render(<PoolEditor kind="artists" initial={[]} document={{revision: 'r', items: []}} catalogNames={[]} onDocument={vi.fn()} onApply={vi.fn()} onClose={vi.fn()} />);
  const input = host.querySelector('input[type=checkbox]')!;
  expect(input.parentElement?.classList.contains('builder-check')).toBe(true);
  expect(input.nextElementSibling?.textContent).toBe('first');
  await act(async () => (input.parentElement as HTMLLabelElement).click());
  expect((input as HTMLInputElement).checked).toBe(true);
});

it('separates service tabs and shows only the artist pool for NovelAI', async () => {
  await render(<ImageExperiments workId="work" active openPresets={vi.fn()} />);
  await click('NovelAI');
  const panels = [...host.querySelectorAll('section')];
  const nai = panels[1];
  expect(nai.querySelector(`select[aria-label="${t('explore.artists')}"]`)).not.toBeNull();
  expect(nai.querySelector(`select[aria-label="${t('explore.models')}"]`)).toBeNull();
  expect(nai.querySelector(`select[aria-label="${t('explore.loras')}"]`)).toBeNull();
  expect(nai.querySelector(`select[aria-label="${t('explore.fixed_model')}"]`)).not.toBeNull();
  expect(post).not.toHaveBeenCalled();
});

it('prepares and confirms actual counts before generating, then claims progression and leaves on navigation', async () => {
  const doc = {id: 'session', revision: 'r', name: 'demo', service: 'comfyui', family: 'anima', pools: {artists: [], models: [], loras: []}, rules: {}, settings: {seed: 42}, positive: 'scene', negative: '', candidates: [], events: [], scores: {}, pair: null};
  vi.stubGlobal('confirm', vi.fn(() => true));
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}')));
  vi.mocked(post).mockImplementation(async (_url, body) => {
    const b = body as Record<string, unknown>;
    return b.action === 'propose' ? {...doc, proposal: {requested: 10, candidates: [{id: 'candidate'}]}} : doc;
  });
  await render(<StyleExplorer openPresets={vi.fn()} />);
  vi.mocked(get).mockImplementation(async url => url.endsWith('/sessions/session') ? doc : []);
  await click(t('builder.start'));
  expect(vi.mocked(post).mock.calls.map(c => (c[1] as Record<string, unknown>).action)).toEqual([undefined, 'automatic', 'propose', 'generate', 'resume']);
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining(t('builder.confirm', {n: 1, count: 10, limit: 30})));
  const resume = vi.mocked(post).mock.calls.at(-1)![1] as Record<string, unknown>;
  expect(String(resume.owner).length).toBeGreaterThanOrEqual(16);
  await render(<StyleExplorer openPresets={vi.fn()} active={false} />);
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/session'), expect.objectContaining({keepalive: true, body: JSON.stringify({action: 'leave', owner: resume.owner})}));
});

it('does not generate or claim automatic progression when the request confirmation is cancelled', async () => {
  vi.stubGlobal('confirm', vi.fn(() => false));
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}')));
  const doc = {id: 'session', revision: 'r', name: 'demo', service: 'comfyui', family: 'anima', pools: {artists: [], models: [], loras: []}, rules: {}, settings: {}, candidates: [], events: [], scores: {}, pair: null};
  vi.mocked(post).mockImplementation(async () => ({...doc, proposal: {requested: 10, candidates: [{id: 'candidate'}]}}));
  await render(<StyleExplorer openPresets={vi.fn()} />);
  vi.mocked(get).mockImplementation(async url => url.endsWith('/sessions/session') ? doc : []);
  await click(t('builder.start'));
  expect(vi.mocked(post).mock.calls.map(c => (c[1] as Record<string, unknown>).action)).toEqual([undefined, 'automatic', 'propose']);
});
