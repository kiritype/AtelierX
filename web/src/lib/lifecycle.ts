// The life cycle every long-running job shares (#89; server: core/lifecycle.py).
// queued → running (phase: which step) → done | failed | cancelled; a cancel goes through cancelling;
// a job cut off by the app closing is interrupted and can be retried.

export const UNFINISHED = ['queued', 'running', 'cancelling'];
export const FINISHED = ['done', 'failed', 'cancelled', 'interrupted'];

export const unfinished = (status: string | undefined) => !!status && UNFINISHED.includes(status);
export const finished = (status: string | undefined) => !!status && FINISHED.includes(status);
// A job that can still be asked to stop (not already stopping).
export const cancellable = (status: string | undefined) => status === 'queued' || status === 'running';
