// The prompt library editor's draft when the selection or the fetched list changes (#167): an edit in progress for
// the selected item is kept (a list fetched again must not replace it); otherwise the stored item is loaded.
export function followSelection<T extends { id: string }>(current: T | null, selected: string | null, stored: T | null): T | null {
  return current && current.id === selected ? current : stored;
}

// When a save answers: the stored version replaces the draft only if the draft is still the one that was sent. An edit
// made while the save was on its way, or another item opened meanwhile, stays as it is.
export function afterSave<T>(current: T | null, sent: T, saved: T | null): T | null {
  return current === sent ? saved : current;
}
