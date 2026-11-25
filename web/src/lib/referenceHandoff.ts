// The gallery and reference screen live in the same work window.
const pendingReferences = new Map<string, string>();

export function sendReferenceHandoff(workId: string, path: string) {
  pendingReferences.set(workId, path);
}

export function takeReferenceHandoff(workId: string) {
  const path = pendingReferences.get(workId);
  pendingReferences.delete(workId);
  return path;
}
