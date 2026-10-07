// Prompt text as a tag list (see tags.js).
export function tagAt(text: string, caret: number): { start: number; end: number; word: string };
export function splitPrompt(text: string): string[];
export function isNote(entry: string): boolean;
export function stripNotes(text: string): string;
export function bracketOpen(text: string): boolean;
export function pasteInto(text: string, start: number, end: number, pasted: string): string;
export function splitTags(text: string): string[];
export const promptTag: (tag: string) => string;
export function replaceTag(text: string, start: number, end: number, tag: string, separator?: string): { text: string; caret: number };
export const MODEL_WORDS: RegExp;
