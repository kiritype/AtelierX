// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError, get, post } from '../../api';
import { t } from '../../i18n';
import StyleExplorer from './StyleExplorer';
import ExplorerCompare from './ExplorerCompare';
import type { ExplorerMaterial, ExplorerSession } from '../../styleExplorerTypes';
import {
  effectiveRules, EXPLORER_DRAFT_KEY, freshDraft, materialPool, readDraft, settingsKey, switchContext,
} from './styleExplorerDraft';
vi.mock('../../api', async (original) => ({
  ...(await original<typeof import('../../api')>()),
  get: vi.fn(),
  post: vi.fn(),
}));
vi.mock('./GenSettings', () => ({
  default: () => null,
  useCatalog: () => ({ data: {
    connected: true,
    models: [],
    loras: ['anima.safetensors', 'sdxl.safetensors', 'unknown.safetensors'],
    families: { loras: { 'anima.safetensors': 'anima', 'sdxl.safetensors': 'sdxl' } },
  } }),
  FAMILY_DEFAULTS: { anima: { steps: 32 }, sdxl: { steps: 28 } },
}));
vi.mock('./NovelAISettings', () => ({
  default: () => null,
  useNovelAIInfo: () => ({ data: { defaults: { model: 'nai' } } }),
}));
vi.mock('./PixAISettings', () => ({
  default: () => null,
  usePixAIInfo: () => ({ data: {
    defaults: { model: 'pixai', loras: [{ id: '999999' }] },
    loras: [{ id: '123456', name: 'Registered LoRA', weight: 0.65, trigger_words: 'default words' }],
    max_loras: 5,
  } }),
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
async function render(props: { workId?: string } = { workId: 'work' }) {
  await act(async () =>
    root.render(
      <QueryClientProvider client={qc}>
        <StyleExplorer {...props} openView={vi.fn()} />
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
  expect(readDraft().name).toBe('Example');
  expect(JSON.parse(localStorage.getItem('atelierx-explorer-v1-work')!)).toEqual(draft);
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
it('migrates prior tag modes and LoRA ranges, and prefers the global draft', () => {
  const legacy = {
    name: 'Legacy setup',
    service: 'comfyui',
    family: 'anima',
    artists: [{ name: 'one', mode: 'exclude' }, { name: 'two', mode: 'always' }],
    rules: { artist_low: 0.9, artist_high: 1.3, artist_step: 0.2, lora_low: 0.3, lora_high: 0.7, lora_step: 0.2 },
    settings: {
      'comfyui:anima': { loras: [{ name: 'anima.safetensors', strength_model: 0.6, trigger_words: 'saved' }] },
      pixai: { loras: [{ id: '123456', weight: 0.7 }, { id: '654321', enabled: false }] },
    },
  };
  const stored = JSON.stringify(legacy);
  localStorage.setItem('atelierx-explorer-v1-work', stored);
  const migrated = readDraft('work');
  expect(materialPool(migrated).materials).toEqual([
    { kind: 'tag', name: 'one', role: 'style', mode: 'exclude', weight: { mode: 'random', low: 0.9, high: 1.3, step: 0.2 } },
    { kind: 'tag', name: 'two', role: 'style', mode: 'always', weight: { mode: 'random', low: 0.9, high: 1.3, step: 0.2 } },
    { kind: 'lora', name: 'anima.safetensors', role: 'style', mode: 'candidate', trigger_words: 'saved',
      weight: { mode: 'random', low: 0.3, high: 0.7, step: 0.2 } },
  ]);
  const pixai = switchContext(migrated, { service: 'pixai' });
  expect(materialPool(pixai).materials.slice(2)).toMatchObject([
    { kind: 'lora', id: '123456', mode: 'candidate', weight: { mode: 'random', low: 0.3, high: 0.7, step: 0.2 } },
    { kind: 'lora', id: '654321', mode: 'exclude' },
  ]);
  expect(migrated.settings.pixai).not.toHaveProperty('loras');
  expect(materialPool(switchContext(migrated, { service: 'novelai' })).materials).toHaveLength(2);
  expect(localStorage.getItem('atelierx-explorer-v1-work')).toBe(stored);
  expect(readDraft().name).toBe('');
  localStorage.setItem(EXPLORER_DRAFT_KEY, JSON.stringify({ ...migrated, name: 'Global setup' }));
  expect(readDraft('work').name).toBe('Global setup');
  expect(readDraft().name).toBe('Global setup');
});

it('does not let an empty global visit take precedence over a legacy work draft', async () => {
  localStorage.setItem('atelierx-explorer-v1-work', JSON.stringify({ name: 'From work', service: 'pixai' }));
  await render({});
  expect(localStorage.getItem(EXPLORER_DRAFT_KEY)).toBeNull();
  expect(readDraft('work').name).toBe('From work');
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

it('bounds total counts to eligible materials, the always floor and the provider limit', () => {
  const draft = freshDraft();
  expect(effectiveRules(draft)).toEqual({ artist_min: 0, artist_max: 0, lora_min: 0, lora_max: 0 });
  const pool = materialPool(draft);
  draft.materialPools[settingsKey(draft)] = pool;
  const weight = { mode: 'fixed', value: 0.8 } as const;
  pool.materials = [
    { kind: 'tag', role: 'character', name: 'fixed', mode: 'always', weight },
    { kind: 'tag', role: 'style', name: 'optional', mode: 'candidate', weight },
    { kind: 'tag', role: 'style', name: 'ignored', mode: 'exclude', weight },
    { kind: 'lora', role: 'character', name: 'fixed LoRA', mode: 'always', weight },
    { kind: 'lora', role: 'style', name: 'optional LoRA', mode: 'candidate', weight },
  ];
  pool.rules.artist_max = 0;
  expect(effectiveRules(draft)).toEqual({ artist_min: 1, artist_max: 1, lora_min: 1, lora_max: 2 });
  pool.rules.artist_max = 3;
  expect(effectiveRules(draft, 1)).toEqual({ artist_min: 1, artist_max: 2, lora_min: 1, lora_max: 1 });
  expect(effectiveRules(switchContext(draft, { service: 'novelai' }))).toEqual({
    artist_min: 0, artist_max: 0, lora_min: 0, lora_max: 0,
  });
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
it('preserves independent model pools, materials and counts across context switches and reloads', () => {
  const initial = { ...freshDraft(), models: 'anima-model' };
  const material: ExplorerMaterial = {
    name: 'Anima style', kind: 'tag', mode: 'candidate', role: 'style', weight: { mode: 'fixed', value: 0.9 },
  };
  initial.materialPools['comfyui:anima'] = {
    materials: [material],
    rules: { artist_min: 0, artist_max: 1, lora_min: 0, lora_max: 0 },
  };
  const novelai = switchContext(initial, { service: 'novelai' });
  expect(novelai.models).toBe('');
  expect(materialPool(novelai).materials).toEqual([]);
  const pixai = switchContext({ ...novelai, models: 'nai-model' }, { service: 'pixai' });
  expect(pixai.models).toBe('');
  const comfy = switchContext({ ...pixai, models: 'pixai-model' }, { service: 'comfyui' });
  expect(comfy.models).toBe('anima-model');
  const sdxl = switchContext(comfy, { family: 'sdxl' });
  expect(sdxl.models).toBe('');
  expect(materialPool(sdxl).materials).toEqual([]);
  const anima = switchContext({ ...sdxl, models: 'sdxl-model' }, { family: 'anima' });
  expect(anima.models).toBe('anima-model');
  localStorage.setItem(EXPLORER_DRAFT_KEY, JSON.stringify(anima));
  const restored = readDraft();
  expect(materialPool(restored)).toEqual(initial.materialPools['comfyui:anima']);
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

async function select(element: HTMLSelectElement, value: string) {
  await act(async () => {
    element.value = value;
    element.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

async function input(element: HTMLInputElement | HTMLTextAreaElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), 'value')!.set!.call(element, value);
    element.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

it('submits tags and registered LoRAs with their own roles, weight modes and triggers', async () => {
  localStorage.setItem(EXPLORER_DRAFT_KEY, JSON.stringify({ ...freshDraft(), name: 'Example', positive: 'scene' }));
  vi.mocked(post).mockResolvedValue(makeSession());
  await render({});
  const picker = () => host.querySelector<HTMLSelectElement>('.explorer-material-add select')!;
  expect([...picker().options].map((option) => option.value)).toEqual(['', 'anima.safetensors']);
  await act(async () => button('SDXL').click());
  expect([...picker().options].map((option) => option.value)).toEqual(['', 'sdxl.safetensors']);
  await act(async () => button('NovelAI').click());
  expect(picker()).toBeNull();
  await act(async () => button('PixAI').click());
  expect([...picker().options].map((option) => option.value)).toEqual(['', '123456']);
  await input(host.querySelector<HTMLTextAreaElement>('.explorer-material-add textarea')!, 'artist:a, artist:a');
  await act(async () => button(t('style_explorer.add_tags')).click());
  await select(picker(), '123456');
  await act(async () => button(t('gen.add_lora')).click());
  const rows = [...host.querySelectorAll<HTMLFieldSetElement>('.explorer-material-row')];
  expect(rows).toHaveLength(2);
  const [role, inclusion, weightMode] = [...rows[1].querySelectorAll('select')];
  await select(role, 'character');
  expect(inclusion.value).toBe('always');
  expect(weightMode.value).toBe('fixed');
  const weight = rows[1].querySelector<HTMLInputElement>('input[type="number"]')!;
  expect(weight.value).toBe('0.65');
  await input(weight, '0.75');
  await input(rows[1].querySelector<HTMLInputElement>('.explorer-trigger-field input')!, 'edited words');
  await act(async () => button(t('style_explorer.review_generate')).click());
  await act(async () => button(t('style_explorer.confirm_action')).click());
  expect(post).toHaveBeenNthCalledWith(1, '/api/image/explorer/sessions', expect.objectContaining({
    service: 'pixai',
    settings: { model: 'pixai' },
    rules: { artist_min: 1, artist_max: 1, lora_min: 1, lora_max: 1 },
    materials: [
      { kind: 'tag', name: 'artist:a', role: 'style', mode: 'candidate', weight: { mode: 'random', low: 0.7, high: 1.2, step: 0.1 } },
      { kind: 'lora', id: '123456', name: 'Registered LoRA', role: 'character', mode: 'always', trigger_words: 'edited words',
        weight: { mode: 'fixed', value: 0.75 } },
    ],
  }));
});

it('lets a saved LoRA with a missing catalog entry stay in the draft as excluded', async () => {
  const draft = { ...freshDraft(), name: 'Example', positive: 'scene' };
  const pool = materialPool(draft);
  const missing: ExplorerMaterial = {
    name: 'missing.safetensors', kind: 'lora', role: 'style', mode: 'candidate', weight: { mode: 'fixed', value: 0.8 },
  };
  pool.materials = [missing];
  draft.materialPools[settingsKey(draft)] = pool;
  localStorage.setItem(EXPLORER_DRAFT_KEY, JSON.stringify(draft));
  vi.mocked(post).mockResolvedValue(makeSession());
  await render({});
  const review = button(t('style_explorer.review_generate'));
  expect(review.disabled).toBe(true);
  const row = host.querySelector('.explorer-material-row')!;
  expect(row.textContent).toContain(t('style_explorer.lora_missing'));
  await select(row.querySelectorAll('select')[1], 'exclude');
  expect(review.disabled).toBe(false);
  await act(async () => review.click());
  await act(async () => button(t('style_explorer.confirm_action')).click());
  expect(post).toHaveBeenNthCalledWith(1, '/api/image/explorer/sessions', expect.objectContaining({
    materials: [{ ...missing, mode: 'exclude' }],
    rules: { artist_min: 0, artist_max: 0, lora_min: 0, lora_max: 0 },
  }));
});
