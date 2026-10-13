import { ApiError, post } from '../api';

export type ToolBatch = {
  id: string; operation: string; total: number; accepted: number; progress: number; created_at: string;
  counts: Record<'pending' | 'queued' | 'running' | 'cancelling' | 'done' | 'failed' | 'cancelled' | 'interrupted', number>;
  paused: boolean; cancelled: boolean;
};
type Submission = { requestId: string; pending?: Promise<ToolBatch> };
const submissions = new Map<string, Submission>();

// A double-click shares one request; retrying an uncertain transport failure keeps its idempotency key.
export function submitToolBatch(operation: string, body: Record<string, unknown>): Promise<ToolBatch> {
  const signature = JSON.stringify({ operation, ...body });
  const submission = submissions.get(signature) ?? { requestId: crypto.randomUUID() };
  if (submission.pending) return submission.pending;
  submissions.set(signature, submission);
  submission.pending = post<ToolBatch>('/api/image/tools/batches', { ...body, operation, request_id: submission.requestId })
    .then((result) => { submissions.delete(signature); return result; })
    .catch((error) => {
      submission.pending = undefined;
      if (error instanceof ApiError && error.status >= 400 && error.status < 500) submissions.delete(signature);
      throw error;
    });
  return submission.pending;
}
