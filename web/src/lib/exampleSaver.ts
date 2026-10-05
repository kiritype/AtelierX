// Autosave of edits that are each stored under a key (a JSX example: the JSX ID and the example name).
// - Writes run one at a time, so the server always receives them in edit order and an older answer can never arrive
//   after a newer one.
// - Every edit raises the version. A finished write is `clean` only when no newer edit came in meanwhile; only a clean
//   answer may update what the screen shows, otherwise the newer text stays on screen and is written next.
// - The key is taken at edit time, so a job always goes where it was typed even if the screen moved on.
// - The saver lives with the item editor, not the preview tab, so switching tabs never cancels a save.

export type SaveJob<K> = { key: K; text: string; version: number };
export type FlushResult = { saved?: unknown; clean: boolean; written: boolean };

export function createSaver<K>(
  put: (key: K, text: string) => Promise<unknown>,
  {
    delay = 700,
    onChange,
    onSaved,
    onError,
  }: {
    delay?: number;
    onChange?: (dirty: boolean) => void;
    // After every write; `clean` says whether the answer may replace what the screen shows.
    onSaved?: (key: K, saved: unknown, clean: boolean) => void;
    // A write started by the timer failed.
    onError?: (error: unknown) => void;
  } = {},
) {
  let version = 0;
  let pending: SaveJob<K> | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let queue: Promise<unknown> = Promise.resolve();
  let disposed = false;
  const notify = () => onChange?.(pending !== null);
  const cancelTimer = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  };

  const saver = {
    edit(key: K, text: string) {
      if (disposed) return;
      version += 1;
      pending = { key, text, version };
      notify();
      cancelTimer();
      timer = setTimeout(() => {
        timer = null;
        saver.flush().catch((error) => onError?.(error));
      }, delay);
    },
    get dirty() {
      return pending !== null;
    },
    get job() {
      return pending;
    },
    // Writes the latest edit after any write already on its way. Rejects when the write fails (the edit stays pending).
    flush(): Promise<FlushResult> {
      cancelTimer();
      const run = queue.then(async (): Promise<FlushResult> => {
        const job = pending;
        if (!job || disposed) return { clean: pending === null, written: false };
        const saved = await put(job.key, job.text);
        if (pending?.version === job.version) pending = null;
        notify();
        onSaved?.(job.key, saved, pending === null);
        return { saved, clean: pending === null, written: true };
      });
      queue = run.catch(() => undefined);
      return run;
    },
    // Resolves once every write already started has finished (a delete must not race a write).
    idle(): Promise<void> {
      return queue.then(() => undefined);
    },
    // Forget unsaved edits of one key (its example was deleted) or of all keys.
    drop(match?: (key: K) => boolean) {
      if (pending && (!match || match(pending.key))) {
        pending = null;
        cancelTimer();
        notify();
      }
    },
    // The editor (re)mounted: React's development StrictMode runs cleanup and setup once more on mount, so setup
    // must undo a dispose for the saver to keep working.
    activate() {
      disposed = false;
    },
    // The editor closed without saving (the user chose to discard): nothing more is written.
    dispose() {
      disposed = true;
      cancelTimer();
      pending = null;
    },
  };
  return saver;
}

export type Saver<K> = ReturnType<typeof createSaver<K>>;
