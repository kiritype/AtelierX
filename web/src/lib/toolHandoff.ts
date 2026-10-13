// One-shot selection for both an already open tools tab and one opened after the toast action.
export const TOOL_HANDOFF = 'atelierx-tools-selection';
let pending: string | null = null;
export function sendToTools(itemId: string) {
  pending = itemId;
  window.dispatchEvent(new CustomEvent(TOOL_HANDOFF));
}
export function takeToolHandoff(): string | null {
  const value = pending;
  pending = null;
  return value;
}
