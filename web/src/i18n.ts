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

export function tm(msg: { key: string; text: string; values?: Record<string, unknown> }): string {
  return current[msg.key] ? t(msg.key, msg.values) : msg.text;
}

export const getLanguage = () => currentLanguage;
