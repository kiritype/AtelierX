// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError, get, post } from '../../api';
import { t } from '../../i18n';
import StyleExplorer from './StyleExplorer';
import ExplorerCompare from './ExplorerCompare';
import type { ExplorerSession } from '../../styleExplorerTypes';
import { freshDraft, parseArtists, settingsKey } from './styleExplorerDraft';
vi.mock('../../api', async (original) => ({
  ...(await original<typeof import('../../api')>()),
  get: vi.fn(),
  post: vi.fn(),
}));
vi.mock('./GenSettings', () => ({
  default: () => null,
  useCatalog: () => ({ data: undefined }),
  FAMILY_DEFAULTS: { anima: { steps: 32 }, sdxl: { steps: 28 } },
}));
vi.mock('./NovelAISettings', () => ({
  default: () => null,
  useNovelAIInfo: () => ({ data: { defaults: { model: 'nai' } } }),
}));
vi.mock('./PixAISettings', () => ({
  default: () => null,
  usePixAIInfo: () => ({ data: { defaults: { model: 'pixai' } } }),
}));
let host: HTMLDivElement, root: Root, qc: QueryClient;
const makeSession = (): ExplorerSession => ({
  id: 's1',
  name: 'Example',
  service: 'comfyui',
  family: 'anima',
  created_at: '',
  budget: 30,
  used: 0,
  candidate_count: 0,
  vote_count: 0,
  revision: 1,
  config: {} as ExplorerSession['config'],
  candidates: [],
  pair: null,
  votes: [],
  ranking: [],
});
const button = (label: string) => [...host.querySelectorAll('button')].find((b) => b.textContent === label)!;
beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(get).mockImplementation(async (url) => {
    if (url.endsWith('/capabilities'))
      return {
        services: [{ id: 'comfyui', enabled: true, families: [] }],
        max_batch: 16,
        max_budget: 200,
        defaults: { count: 8, budget: 30 },
      };
    if (url === '/api/image/services') return { services: [] };
    if (url.endsWith('/sessions')) return { sessions: [] };
    return makeSession();
  });
});
afterEach(async () => {
  await act(async () => root.unmount());
  qc.clear();
  host.remove();
});
async function render() {
  await act(async () =>
    root.render(
      <QueryClientProvider client={qc}>
        <StyleExplorer workId="work" openView={vi.fn()} />
      </QueryClientProvider>,
    ),
  );
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
}
it('never generates on entry, keeps MOSS disabled, and generates only after reviewing count and budget', async () => {
  const draft = { ...freshDraft(), name: 'Example', positive: '1girl' };
  localStorage.setItem('atelierx-explorer-v1-work', JSON.stringify(draft));
  vi.mocked(post).mockResolvedValue(makeSession());
  await render();
  expect(post).not.toHaveBeenCalled();
  const moss = [...host.querySelectorAll('button')].find((b) => b.textContent?.includes('MOSS'));
  expect(moss?.disabled).toBe(true);
  await act(async () => button(t('style_explorer.review_generate')).click());
  expect(post).not.toHaveBeenCalled();
  expect(host.querySelector('[role="dialog"]')?.textContent).toContain(
    t('style_explorer.confirm_generate', { count: 8, budget: 30 }),
  );
  await act(async () => button(t('style_explorer.confirm_action')).click());
  expect(post).toHaveBeenNthCalledWith(
    1,
    '/api/image/explorer/sessions',
    expect.objectContaining({ name: 'Example', budget: 30, positive: '1girl' }),
  );
  expect(post).toHaveBeenNthCalledWith(
    2,
    '/api/image/explorer/sessions/s1/generate',
    expect.objectContaining({ count: 8, revision: 1 }),
  );
});
it('keeps the created session visible when generating fails', async () => {
  localStorage.setItem(
    'atelierx-explorer-v1-work',
    JSON.stringify({ ...freshDraft(), name: 'Example', positive: 'scene' }),
  );
  vi.mocked(post)
    .mockResolvedValueOnce(makeSession())
    .mockRejectedValueOnce(new ApiError(503, { key: 'test.error', text: 'Offline' }));
  await render();
  await act(async () => button(t('style_explorer.review_generate')).click());
  await act(async () => button(t('style_explorer.confirm_action')).click());
  expect(host.textContent).toContain(t('style_explorer.created_generate_failed'));
  expect(host.textContent).toContain('Example');
  expect(post).toHaveBeenCalledTimes(2);
});
it('preserves artist modes and separates settings for each ComfyUI family', () => {
  expect(parseArtists('one\ntwo\none', [{ name: 'one', mode: 'exclude' }])).toEqual([
    { name: 'one', mode: 'exclude' },
    { name: 'two', mode: 'candidate' },
  ]);
  expect(settingsKey({ service: 'comfyui', family: 'anima' })).not.toBe(
    settingsKey({ service: 'comfyui', family: 'sdxl' }),
  );
});
it('hides generation recipes, scopes shortcuts to the comparator, and blocks votes for broken images', async () => {
  const vote = vi.fn();
  const s = makeSession();
  s.candidates = ['a', 'b'].map((id, index) => ({
    id,
    index,
    status: 'done',
    image_url: `/${id}.png`,
    positive: 'secret recipe',
    negative: '',
    settings: { model: 'hidden model' },
    artists: [],
    seed: 4,
    elo: 1200,
    matches: 0,
    wins: 0,
    draws: 0,
    rejected: 0,
  }));
  s.pair = { id: 'pair', a: 'a', b: 'b' };
  await act(async () => root.render(<ExplorerCompare session={s} busy={false} vote={vote} />));
  expect(host.textContent).not.toContain('hidden model');
  expect(host.textContent).not.toContain('secret recipe');
  await act(async () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true })));
  expect(vote).not.toHaveBeenCalled();
  await act(async () =>
    host.querySelector('section')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true })),
  );
  expect(vote).toHaveBeenCalledWith('a');
  await act(async () => host.querySelector('img')!.dispatchEvent(new Event('error')));
  expect([...host.querySelectorAll('.explorer-choice')].every((b) => (b as HTMLButtonElement).disabled)).toBe(true);
  await act(async () => button(t('style_explorer.reveal')).click());
  expect(host.textContent).toContain('hidden model');
});

it('clamps displayed recipe counts to eligible pools, including always artists and no NovelAI LoRAs', async () => {
  const { effectiveRules } = await import('./styleExplorerDraft');
  const d = freshDraft();
  expect(effectiveRules(d)).toMatchObject({
    artist_min: 0,
    artist_max: 0,
    lora_min: 0,
    lora_max: 0,
  });
  d.artists = [
    { name: 'fixed', mode: 'always' },
    { name: 'optional', mode: 'candidate' },
    { name: 'ignored', mode: 'exclude' },
  ];
  d.rules.artist_max = 0;
  expect(effectiveRules(d).artist_max).toBe(1);
  d.rules.artist_max = 3;
  expect(effectiveRules(d).artist_max).toBe(2);
  d.service = 'novelai';
  d.settings.novelai = { loras: [{ name: 'ignored' }] };
  expect(effectiveRules(d)).toMatchObject({ lora_min: 0, lora_max: 0 });
});
it('requests a new pair when more images complete without a session revision change', async () => {
  const s = makeSession();
  s.candidates = ['a', 'b'].map((id, index) => ({
    id,
    index,
    status: 'done',
    image_url: `/${id}.png`,
    positive: '',
    negative: '',
    settings: {},
    artists: [],
    seed: 4,
    elo: 1200,
    matches: 0,
    wins: 0,
    draws: 0,
    rejected: 0,
  }));
  s.votes = [{ id: 'vote', pair_id: 'p', a: 'a', b: 'b', result: 'a', created_at: '' }];
  qc.setQueryData(['explorer-session', 's1'], s);
  vi.mocked(get).mockImplementation(async (url) => {
    if (url.endsWith('/capabilities'))
      return {
        services: [],
        max_batch: 16,
        max_budget: 200,
        defaults: { count: 8, budget: 30 },
      };
    if (url === '/api/image/services') return { services: [] };
    if (url.endsWith('/sessions')) return { sessions: [s] };
    return s;
  });
  vi.mocked(post).mockResolvedValue(s);
  await render();
  await act(async () =>
    [...host.querySelectorAll('button')].find((b) => b.textContent?.startsWith('Example'))!.click(),
  );
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
  expect(post).toHaveBeenCalledTimes(1);
  expect(host.textContent).toContain(t('style_explorer.completed'));
  const next = {
    ...s,
    candidates: [...s.candidates, { ...s.candidates[0], id: 'c' }],
  };
  vi.mocked(post).mockResolvedValue(next);
  await act(async () => qc.setQueryData(['explorer-session', 's1'], next));
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
  expect(post).toHaveBeenCalledTimes(2);
  expect(post).toHaveBeenLastCalledWith(
    '/api/image/explorer/sessions/s1/pair',
    expect.objectContaining({ revision: 1 }),
  );
});
it('preserves model pools separately across service and family switches and browser draft reloads', async () => {
  const { switchContext, readDraft } = await import('./styleExplorerDraft');
  const initial = { ...freshDraft(), models: 'anima-model', artists: [{ name: 'shared', mode: 'candidate' as const }] };
  const novelai = switchContext(initial, { service: 'novelai' });
  expect(novelai.models).toBe('');
  const pixai = switchContext({ ...novelai, models: 'nai-model' }, { service: 'pixai' });
  expect(pixai.models).toBe('');
  const comfy = switchContext({ ...pixai, models: 'pixai-model' }, { service: 'comfyui' });
  expect(comfy.models).toBe('anima-model');
  const sdxl = switchContext(comfy, { family: 'sdxl' });
  expect(sdxl.models).toBe('');
  const anima = switchContext({ ...sdxl, models: 'sdxl-model' }, { family: 'anima' });
  expect(anima.models).toBe('anima-model');
  expect(anima.artists).toEqual(initial.artists);
  expect(anima.rules).toEqual(initial.rules);
  localStorage.setItem('model-pools', JSON.stringify(anima));
  const restored = readDraft('model-pools');
  expect(switchContext(restored, { family: 'sdxl' }).models).toBe('sdxl-model');
  expect(switchContext(restored, { service: 'novelai' }).models).toBe('nai-model');
  expect(switchContext(restored, { service: 'pixai' }).models).toBe('pixai-model');
});
it('does not submit ComfyUI model candidates after selecting NovelAI', async () => {
  localStorage.setItem(
    'atelierx-explorer-v1-work',
    JSON.stringify({ ...freshDraft(), name: 'Example', positive: 'scene', models: 'comfy-model' }),
  );
  vi.mocked(post).mockResolvedValue(makeSession());
  await render();
  await act(async () => button('NovelAI').click());
  await act(async () => button(t('style_explorer.review_generate')).click());
  await act(async () => button(t('style_explorer.confirm_action')).click());
  expect(post).toHaveBeenNthCalledWith(
    1,
    '/api/image/explorer/sessions',
    expect.objectContaining({ service: 'novelai', models: [] }),
  );
});
