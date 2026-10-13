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
