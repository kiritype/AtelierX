import { expect, it, vi } from 'vitest';
import { post } from '../api';
import { submitToolBatch } from './toolBatches';

vi.mock('../api', async original => ({ ...await original<typeof import('../api')>(), post: vi.fn() }));

it('shares concurrent submissions without truncating 8000 targets and reuses uncertain request IDs', async () => {
  const ids = Array.from({ length: 8000 }, (_, i) => String(i));
  let reject!: (reason: unknown) => void;
  vi.mocked(post).mockImplementationOnce(() => new Promise((_, fail) => { reject = fail; }));
  const first = submitToolBatch('tag', { ids });
  const repeated = submitToolBatch('tag', { ids });
  expect(repeated).toBe(first);
  const body = vi.mocked(post).mock.calls[0][1] as { ids: string[]; request_id: string };
  expect(body.ids).toHaveLength(8000);
  reject(new TypeError('connection lost'));
  await expect(first).rejects.toThrow('connection lost');
  vi.mocked(post).mockResolvedValueOnce({ id: 'accepted' });
  await submitToolBatch('tag', { ids });
  expect((vi.mocked(post).mock.calls[1][1] as { request_id: string }).request_id).toBe(body.request_id);
});

it('uses a fresh request ID only for an explicit rerun after acceptance', async () => {
  vi.mocked(post).mockResolvedValue({ id: 'accepted' });
  await submitToolBatch('tag', { ids: ['rerun-target'] });
  await submitToolBatch('tag', { ids: ['rerun-target'] }, true);
  const calls = vi.mocked(post).mock.calls.slice(-2);
  expect((calls[0][1] as { request_id: string }).request_id).not.toBe((calls[1][1] as { request_id: string }).request_id);
  expect((calls[1][1] as { rerun: boolean }).rerun).toBe(true);
});

it('keeps the explicit rerun request ID after an uncertain response', async () => {
  vi.mocked(post).mockRejectedValueOnce(new TypeError('connection lost'));
  await expect(submitToolBatch('tag', { ids: ['uncertain-rerun'] }, true)).rejects.toThrow('connection lost');
  const first = (vi.mocked(post).mock.calls.at(-1)![1] as { request_id: string }).request_id;
  vi.mocked(post).mockResolvedValueOnce({ id: 'accepted' });
  await submitToolBatch('tag', { ids: ['uncertain-rerun'] }, true);
  const retried = (vi.mocked(post).mock.calls.at(-1)![1] as { request_id: string }).request_id;
  expect(retried).toBe(first);
});
