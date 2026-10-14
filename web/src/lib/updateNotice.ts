export type UpdateSummary = { current: string; latest: string; newer: boolean };

let inFlight: Promise<unknown> | null = null;

// A screen may unmount during the request. Keep the promise shared so the next screen can receive its result.
export function beginStartupUpdateCheck<T>(check: () => Promise<T>): Promise<T> {
  if (inFlight) return inFlight as Promise<T>;
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
