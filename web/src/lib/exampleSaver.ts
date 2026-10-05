// Autosave of one editor buffer that may be saved under different names (JSX examples).
// Every edit raises the version; a save only marks the buffer clean when no newer edit came in while it was on its
// way, so a late answer never ends editing or replaces newer text.

export type SaveJob = { name: string; text: string; version: number };

export function createSaver(put: (name: string, text: string) => Promise<unknown>) {
  let version = 0;
  let pending: SaveJob | null = null;
  return {
    edit(name: string, text: string) {
      version += 1;
      pending = { name, text, version };
    },
    get dirty() {
      return pending !== null;
    },
    get job() {
      return pending;
    },
    // Saves the latest edit. `clean` is true only when nothing newer is waiting afterwards.
    async flush(): Promise<{ saved?: unknown; clean: boolean }> {
      const job = pending;
      if (!job) return { clean: true };
      const saved = await put(job.name, job.text);
      if (pending && pending.version === job.version) pending = null;
      return { saved, clean: pending === null };
    },
    drop() {
      pending = null;
    },
  };
}
