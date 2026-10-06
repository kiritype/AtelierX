// Thin fetch wrapper. Server errors arrive as {error: {key, text, values}} (architecture: 요청과 이벤트).

export type ServerMessage = { key: string; text: string; values?: Record<string, unknown> };

export class ApiError extends Error {
  status: number;
  msg: ServerMessage;
  constructor(status: number, msg: ServerMessage) {
    super(msg.text);
    this.status = status;
    this.msg = msg;
  }
}

let onUnauthorized: () => void = () => {};
// Asked before a work's contents go to an external LLM connection the first time (03-llm: 외부 전송 확인).
// Returns true when the user agreed and the consent was recorded, so the request can be sent again.
let onConsentNeeded: (msg: ServerMessage, url: string) => Promise<boolean> = async () => false;
export function setConsentHandler(fn: (msg: ServerMessage, url: string) => Promise<boolean>) {
  onConsentNeeded = fn;
}

export const askConsent = (msg: ServerMessage, url: string) => onConsentNeeded(msg, url);

export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

// For requests made outside `api` (streams) that find the session gone.
export const notifyUnauthorized = () => onUnauthorized();

export async function api<T = any>(method: string, url: string, body?: unknown, retried = false): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: 'same-origin',
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    if (response.status === 401 && !url.startsWith('/api/auth/')) onUnauthorized();
    if (response.status === 428 && !retried && data?.error?.key === 'server.llm.consent_needed' && (await onConsentNeeded(data.error, url))) {
      return api<T>(method, url, body, true);
    }
    throw new ApiError(response.status, data?.error ?? { key: 'error.unknown', text: response.statusText });
  }
  return data as T;
}

export const get = <T = any>(url: string) => api<T>('GET', url);
export const post = <T = any>(url: string, body?: unknown) => api<T>('POST', url, body ?? {});
export const put = <T = any>(url: string, body?: unknown) => api<T>('PUT', url, body ?? {});
export const patch = <T = any>(url: string, body?: unknown) => api<T>('PATCH', url, body ?? {});
export const del = <T = any>(url: string) => api<T>('DELETE', url);

export const q = (value: string) => encodeURIComponent(value);

// "연결 이름 · 모델" for a task, from the providers settings (03-llm: 작업별 기본 모델).
export function llmLabel(doc: any, task: string): string {
  if (!doc) return '';
  const setting = doc.tasks?.[task] ?? {};
  const provider = doc.providers?.[setting.provider ?? 'local'];
  if (!provider) return '';
  const model = setting.model ?? provider.default_model;
  return provider.type === 'mock' ? provider.name : `${provider.name} · ${model ?? '?'}`;
}
