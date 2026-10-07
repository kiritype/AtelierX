// Semantic keys with a language catalog. Server messages bring {key, text}; known keys are translated here,
// otherwise the server's English text is shown.
import en from './locales/en.json';
import ko from './locales/ko.json';

type Catalog = Record<string, string>;
const catalogs: Record<string, Catalog> = { ko, en };
let current: Catalog = ko;
let currentLanguage = 'ko';

export function setLanguage(lang: string) {
  current = catalogs[lang] ?? ko;
  currentLanguage = catalogs[lang] ? lang : 'ko';
  document.documentElement.lang = lang;
}

export function t(key: string, values?: Record<string, unknown>): string {
  let text = current[key] ?? ko[key as keyof typeof ko] ?? key;
  if (values) for (const [name, value] of Object.entries(values)) text = text.replaceAll(`{${name}}`, String(value));
  return text;
}

export type ServerMsg = { key: string; text: string; values?: Record<string, unknown> };
const isMsg = (value: unknown): value is ServerMsg =>
  !!value && typeof value === 'object' && typeof (value as ServerMsg).key === 'string' && typeof (value as ServerMsg).text === 'string';

// A value can itself be a server message (the cause inside "Cannot connect: {error}"); it is translated too.
export function tm(msg: ServerMsg): string {
  if (!current[msg.key]) return msg.text;
  const values = msg.values && Object.fromEntries(Object.entries(msg.values).map(([name, value]) => [name, isMsg(value) ? tm(value) : value]));
  return t(msg.key, values);
}

// A server message translated, or any other value as text (an error string, a number, nothing).
export const msgText = (value: unknown): string => (isMsg(value) ? tm(value) : String(value ?? ''));

export const getLanguage = () => currentLanguage;
