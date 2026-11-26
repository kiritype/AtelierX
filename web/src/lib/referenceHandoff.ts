// The gallery and reference screen live in the same work window.
import type { ReferenceSlot } from '../imageTypes';

const requestedSlots = new Map<string, ReferenceSlot>();
const pendingReferences = new Map<string, { path: string; slot: ReferenceSlot }>();

export function pickReferenceFromGallery(workId: string, slot: ReferenceSlot) {
  requestedSlots.set(workId, slot);
}

export function clearReferenceGalleryRequest(workId: string) {
  requestedSlots.delete(workId);
}

export function sendReferenceHandoff(workId: string, path: string) {
  pendingReferences.set(workId, { path, slot: requestedSlots.get(workId) ?? 'a' });
  clearReferenceGalleryRequest(workId);
}

export function takeReferenceHandoff(workId: string) {
  const path = pendingReferences.get(workId);
  pendingReferences.delete(workId);
  return path;
}
