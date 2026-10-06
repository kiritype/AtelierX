// The generate screen's image services (#41): their names, the props of each internet service's settings panel, and
// the last service and settings remembered (each service keeps its own).

export type ServicePanelProps = { value: Record<string, unknown>; onChange: (value: Record<string, unknown>) => void };

export const SERVICE_NAMES: Record<string, string> = { comfyui: 'ComfyUI', novelai: 'NovelAI', pixai: 'PixAI' };

const SERVICE_KEY = (workId: string) => `atelierx-gen-service-${workId}`;
const SETTINGS_KEY = 'atelierx-gen-service-settings';

// The service a work generated with last; the character screen's Generate button opens with it.
export function lastService(workId: string): string {
  try {
    return localStorage.getItem(SERVICE_KEY(workId)) || 'comfyui';
  } catch {
    return 'comfyui';
  }
}

export function rememberService(workId: string, service: string) {
  try {
    localStorage.setItem(SERVICE_KEY(workId), service);
  } catch {
    // remembering is a convenience only
  }
}

export function lastServiceSettings(): Record<string, Record<string, unknown>> {
  try {
    const value = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
    return value && typeof value === 'object' ? value : {};
  } catch {
    return {};
  }
}

export function rememberServiceSettings(all: Record<string, Record<string, unknown>>) {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(all));
  } catch {
    // remembering is a convenience only
  }
}
