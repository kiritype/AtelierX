// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { post } from '../api';
import { t } from '../i18n';
import { postStream } from '../lib/stream';
import TestScreen from './TestScreen';

vi.mock('../api', async (original) => ({ ...await original<typeof import('../api')>(), post: vi.fn() }));
vi.mock('../lib/stream', async (original) => ({ ...await original<typeof import('../lib/stream')>(), postStream: vi.fn() }));

const workId = 'W001';
const persona = { name: '소연', description: '도서관 사서' };
const opening = { role: 'assistant', text: '소연 님, 도서관에 오신 것을 환영합니다.' };
const lorebook = [
  { path: 'library.md', id: 'L001', name: 'Library', kind: 'lorebook' },
  { path: 'visitor.md', id: 'C001', name: 'Visitor', kind: 'character' },
  { path: 'archive.md', id: 'L002', name: 'Archive', kind: 'lorebook' },
  { path: 'annex.md', id: 'L003', name: 'Annex', kind: 'lorebook' },
];
const context = {
  main: 'main.md',
  picked: [
    { ...lorebook[0], reason: 'keyword', keyword: '도서관', size: 20 },
    { ...lorebook[1], reason: 'always', keyword: null, size: 20 },
  ],
  skipped: [{ ...lorebook[2], why: 'budget' }, { ...lorebook[3], why: 'max_active' }],
  lorebook,
  components: [{ path: 'Status.jsx', id: 'J001', name: 'Status' }],
  system: 'Test context',
  system_size: 12,
};

let host: HTMLDivElement;
let root: Root;
let client: QueryClient;
const openItem = vi.fn();

beforeEach(() => {
  vi.resetAllMocks();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(['work', workId], { effective: { values: {} } });
  client.setQueryData(['tree', workId], [
    { type: 'item', kind: 'start', name: 'Opening', path: 'start.md' },
    { type: 'item', kind: 'start', name: 'Alternative', path: 'other.md' },
  ]);
  client.setQueryData(['file', workId, 'start.md'], { body: '{{user}} 님, 도서관에 오신 것을 환영합니다.' });
  client.setQueryData(['file', workId, 'other.md'], { body: '자료실에 오신 것을 환영합니다.' });
  client.setQueryData(['personas'], { personas: [{ id: 'p01', ...persona }], revision: 'first' });
  client.setQueryData(['ui-state'], { persona_by_work: { [workId]: 'p01' } });
  client.setQueryData(['providers'], { providers: {}, tasks: {} });
});

afterEach(async () => {
  await act(async () => root.unmount());
  client.clear();
  host.remove();
});

const render = (active = true) => act(async () => {
  root.render(<QueryClientProvider client={client}><TestScreen workId={workId} active={active} openItem={openItem} /></QueryClientProvider>);
});
const button = (key: string) => [...host.querySelectorAll('button')].find((node) => node.textContent === t(key))!;
const side = () => host.querySelector('.test-side')!;

function enter(value: string) {
  const input = host.querySelector('textarea')!;
  return act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

it('previews the same turn that send uses, without making a model request or replacing recorded context', async () => {
  vi.mocked(post).mockResolvedValue(context);
  vi.mocked(postStream).mockImplementation(async (_url, _body, _signal, event) => {
    event({ type: 'context', data: JSON.stringify({ ...context, system: 'Sent context' }) });
    event({ type: 'delta', data: JSON.stringify('A reply') });
  });
  await render();
  expect(button('test.preview').disabled).toBe(true);
  await enter('  도서관이 어디 있나요?  ');
  await act(async () => button('test.preview').click());

  const payload = { message: '도서관이 어디 있나요?', history: [opening], persona };
  expect(post).toHaveBeenCalledExactlyOnceWith(`/api/works/${workId}/chat/preview`, payload);
  expect(postStream).not.toHaveBeenCalled();
  expect(host.querySelector('textarea')?.value).toBe('  도서관이 어디 있나요?  ');
  expect(side().textContent).toContain(t('test.preview_title'));
  expect(side().textContent).toContain(t('test.keyword', { k: '도서관' }));
  expect(side().textContent).toContain(t('test.always'));
  expect(side().textContent).toContain(t('chat.skip.budget'));
  expect(side().textContent).toContain(t('chat.skip.max_active'));
  expect(side().textContent).not.toContain('Status');
  await act(async () => [...side().querySelectorAll('a')].find((a) => a.textContent === 'Library')!.click());
  expect(openItem).toHaveBeenCalledWith('library.md');

  await act(async () => button('chat.send').click());
  expect(postStream).toHaveBeenCalledExactlyOnceWith(
    `/api/works/${workId}/chat/send`, { ...payload, llm: undefined }, expect.any(AbortSignal), expect.any(Function),
  );
  expect(side().textContent).toContain(t('test.loaded'));
  expect(side().textContent).toContain('Sent context');
  expect(side().textContent).toContain('Status');
  expect(host.querySelector('.chat-log')?.textContent).toContain('A reply');

  await enter('두 번째 질문');
  await act(async () => button('test.preview').click());
  expect(post).toHaveBeenLastCalledWith(`/api/works/${workId}/chat/preview`, {
    message: '두 번째 질문',
    history: [opening, { role: 'user', text: payload.message }, { role: 'assistant', text: 'A reply' }],
    persona,
  });
  await act(async () => host.querySelector<HTMLElement>('.msg.bot.focus')!.click());
  expect(side().textContent).toContain('Sent context');
  expect(side().textContent).not.toContain(t('test.preview_title'));
});

it('drops late successes and errors after editing or leaving the test screen', async () => {
  let finish!: (value: typeof context) => void;
  let fail!: (reason: Error) => void;
  vi.mocked(post)
    .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }))
    .mockResolvedValueOnce({ ...context, system: 'Current preview' })
    .mockImplementationOnce(() => new Promise((_resolve, reject) => { fail = reject; }));
  await render();
  await enter('First message');
  await act(async () => button('test.preview').click());
  expect(side().querySelector('[role=status]')?.textContent).toBe(t('test.preview_loading'));
  await enter('Second message');
  expect(side().textContent).toContain(t('test.loaded_empty'));
  await act(async () => button('test.preview').click());
  await act(async () => finish(context));
  expect(side().textContent).toContain('Current preview');
  expect(side().textContent).not.toContain('Test context');

  await act(async () => button('test.preview').click());
  await render(false);
  await act(async () => fail(new Error('Previous request failed.')));
  await render();
  expect(side().textContent).toContain(t('test.loaded_empty'));
  expect(side().querySelector('[role=alert]')).toBeNull();
  expect(host.querySelector('textarea')?.value).toBe('Second message');
  expect(postStream).not.toHaveBeenCalled();
});

it('rechecks matches using the new opening or persona', async () => {
  vi.mocked(post).mockResolvedValue(context);
  await render();
  await enter('Find a book');
  await act(async () => button('test.preview').click());
  await act(async () => host.querySelector<HTMLButtonElement>('.start-slider button:last-child')!.click());
  expect(side().textContent).toContain(t('test.loaded_empty'));
  await act(async () => button('test.preview').click());
  expect(post).toHaveBeenLastCalledWith(`/api/works/${workId}/chat/preview`, {
    message: 'Find a book',
    history: [{ role: 'assistant', text: '자료실에 오신 것을 환영합니다.' }],
    persona,
  });
  await act(async () => client.setQueryData(['ui-state'], { persona_by_work: { [workId]: null } }));
  await vi.waitFor(() => expect(side().textContent).toContain(t('test.loaded_empty')));
  await act(async () => button('test.preview').click());
  expect(post).toHaveBeenLastCalledWith(`/api/works/${workId}/chat/preview`, {
    message: 'Find a book',
    history: [{ role: 'assistant', text: '자료실에 오신 것을 환영합니다.' }],
    persona: null,
  });
});
