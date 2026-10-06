// Unsaved changes (#88): every editing screen registers what it has not saved yet, under the tab it lives in, and
// optionally how to save it. Closing tabs, leaving the work and locking ask this one register.

export type UnsavedEntry = { dirty: boolean; save?: () => Promise<boolean> };

export class UnsavedRegistry {
  private tabs = new Map<string, Map<string, UnsavedEntry>>();
  private listeners = new Set<() => void>();
  private version = 0;

  set(tab: string, key: string, entry: UnsavedEntry | null) {
    const entries = this.tabs.get(tab) ?? new Map<string, UnsavedEntry>();
    const before = entries.get(key);
    if (entry) entries.set(key, entry);
    else entries.delete(key);
    if (entries.size) this.tabs.set(tab, entries);
    else this.tabs.delete(tab);
    if (before?.dirty !== entry?.dirty || !!before?.save !== !!entry?.save) this.changed();
  }

  // Whether a tab has anything unsaved.
  dirty(tab: string) {
    return [...(this.tabs.get(tab)?.values() ?? [])].some((entry) => entry.dirty);
  }

  dirtyTabs(tabs: string[]) {
    return tabs.filter((tab) => this.dirty(tab));
  }

  // Whether everything unsaved in a tab can be saved from outside (each dirty entry gave a save).
  canSave(tab: string) {
    return [...(this.tabs.get(tab)?.values() ?? [])].every((entry) => !entry.dirty || !!entry.save);
  }

  // Save every dirty entry of a tab; false at the first that could not be saved.
  async save(tab: string) {
    for (const entry of [...(this.tabs.get(tab)?.values() ?? [])]) {
      if (entry.dirty && !(entry.save && (await entry.save()))) return false;
    }
    return true;
  }

  forget(tab: string) {
    if (this.tabs.delete(tab)) this.changed();
  }

  // Follow tabs whose key changed (a file renamed or moved).
  rename(remap: (tab: string) => string) {
    const next = new Map<string, Map<string, UnsavedEntry>>();
    for (const [tab, entries] of this.tabs) next.set(remap(tab), entries);
    this.tabs = next;
    this.changed();
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  snapshot = () => this.version;

  private changed() {
    this.version += 1;
    for (const listener of this.listeners) listener();
  }
}
