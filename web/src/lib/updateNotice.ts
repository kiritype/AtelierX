export type UpdateSummary = { current: string; latest: string; newer: boolean };
export type UpdateNoticeState = { should_check: boolean; available_version: string | null };

let inFlight: Promise<UpdateSummary> | null = null;

// A screen may unmount during the request. Keep the promise shared so the next screen can receive its result.
export function beginStartupUpdateCheck(check: () => Promise<UpdateSummary>) {
  if (inFlight) return inFlight;
  const started = Promise.resolve()
    .then(check)
    .finally(() => {
      if (inFlight === started) inFlight = null;
    });
  inFlight = started;
  return started;
}

export function updateResultKey(result: { state: 'ok' | 'failed'; version?: string; from?: string }) {
  return `${result.state}:${result.version ?? ''}:${result.from ?? ''}`;
}
