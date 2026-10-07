// Prompt text as a tag list separated by commas or line breaks: finding, splitting and
// replacing tags.

/** The tag the caret is in: ``{start, end, word}`` with surrounding spaces trimmed. */
export function tagAt(text, caret) {
  let start = Math.max(text.lastIndexOf(',', caret - 1), text.lastIndexOf('\n', caret - 1)) + 1;
  const ends = [text.indexOf(',', caret), text.indexOf('\n', caret)].filter((i) => i >= 0);
  let end = ends.length ? Math.min(...ends) : text.length;
  while (start < end && /\s/.test(text[start])) start++;
  while (end > start && /\s/.test(text[end - 1])) end--;
  return {start, end, word: text.slice(start, end)};
}

// A note (#157): a "#" that starts a tag (line start, after a comma or a space) runs to the end of the line and is never
// sent. A "#" inside a tag is part of it; a tag that starts with "#" is written "\#compass". Same rule as the server.
const NOTE = /(?:^|(?<=[\s,]))#/;

/** True for an entry that is a note. */
export function isNote(entry) {
  return String(entry || '').trimStart().startsWith('#');
}

/** Prompt text without notes, as the server sends it: a note ends its line, a line left empty goes. */
export function stripNotes(text) {
  const lines = [];
  for (const line of String(text || '').split(/\r?\n/)) {
    const found = NOTE.exec(line);
    let kept = (found ? line.slice(0, found.index) : line).replaceAll('\\#', '#');
    kept = found ? kept.replace(/[\s,]+$/, '') : kept.trimEnd();
    if (kept.trim()) lines.push(kept);
  }
  return lines.join('\n').trim();
}

/**
 * Prompt text as entries to keep, in order (#148): split at commas and line breaks that are outside brackets, so a
 * weighted group "(upper body, straight-on:1.4)" stays whole. Escaped brackets ("\(") do not count; entries are
 * trimmed, empty ones dropped and repeats kept once. Weights and escapes are kept as written.
 */
export function splitPrompt(text) {
  const out = [];
  let depth = 0;
  let current = '';
  const push = () => {
    const entry = current.trim();
    if (entry && !out.includes(entry)) out.push(entry);
    current = '';
  };
  const s = String(text || '');
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (ch === '\\' && i + 1 < s.length) {
      current += ch + s[++i];
      continue;
    }
    // A note keeps the rest of its line, commas included, as one entry (#157).
    if (ch === '#' && depth === 0 && (!current.trim() || /\s$/.test(current))) {
      push();
      const end = s.slice(i).search(/\r?\n/);
      current = end < 0 ? s.slice(i) : s.slice(i, i + end);
      i = end < 0 ? s.length : i + end;
      push();
      continue;
    }
    if ('([{'.includes(ch)) depth++;
    else if (')]}'.includes(ch)) depth = Math.max(0, depth - 1);
    if ((ch === ',' || ch === '\n' || ch === '\r') && depth === 0) push();
    else current += ch;
  }
  push();
  return out;
}

/** ``text`` with ``[start, end)`` (the selection, or the caret when equal) replaced by ``pasted``. */
export function pasteInto(text, start, end, pasted) {
  const from = Math.max(0, Math.min(start, text.length));
  const to = Math.max(from, Math.min(end, text.length));
  return text.slice(0, from) + pasted + text.slice(to);
}

/** True while a bracket is left open (escaped brackets aside): typing a comma there does not end the entry. */
export function bracketOpen(text) {
  let depth = 0;
  const s = String(text || '');
  for (let i = 0; i < s.length; i++) {
    if (s[i] === '\\') i++;
    else if ('([{'.includes(s[i])) depth++;
    else if (')]}'.includes(s[i])) depth = Math.max(0, depth - 1);
  }
  return depth > 0;
}

/** Tags of a prompt in order, without weights or escapes: "(smile:1.2)" -> "smile". */
export function splitTags(text) {
  return stripNotes(text)
    .split(/[,\n]/)
    .map((tag) => unwrap(tag.trim().replace(/:[\d.]+(?=[)\]}]*$)/, '')).replace(/\\([()])/g, '$1'))
    .filter(Boolean);
}

// Drop weight brackets around a tag but keep its own: "(n_(artist))" -> "n_(artist)".
function unwrap(tag) {
  const opened = (value) => (value.match(/(?<!\\)[([{]/g) || []).length;
  const closed = (value) => (value.match(/(?<!\\)[)\]}]/g) || []).length;
  let value = tag;
  while (/^[([{]/.test(value) && opened(value) > closed(value)) value = value.slice(1);
  while (/(?<!\\)[)\]}]$/.test(value) && closed(value) > opened(value)) value = value.slice(0, -1);
  while (wrapped(value)) value = value.slice(1, -1).trim();
  return value.trim();
}

// True when the first bracket closes only at the very end: "(a, (b))" but not "(a) (b)".
function wrapped(value) {
  if (!/^[([{]/.test(value) || !/[)\]}]$/.test(value)) return false;
  let depth = 0;
  for (let i = 0; i < value.length; i++) {
    if ('([{'.includes(value[i])) depth++;
    else if (')]}'.includes(value[i])) depth--;
    if (depth === 0 && i < value.length - 1) return false;
  }
  return depth === 0;
}

/** A Danbooru tag as prompt text: spaces for underscores, parentheses escaped. */
export const promptTag = (tag) => tag.replace(/_/g, ' ').replace(/([()])/g, '\\$1');

/**
 * ``text`` with ``[start, end)`` replaced by ``tag``; returns the text and the new caret.
 * ``separator`` follows the tag unless the next tag already starts there; one-tag-per-line
 * fields pass ''.
 */
export function replaceTag(text, start, end, tag, separator = ', ') {
  const after = text.slice(end);
  const joined = /^[ \t]*[,\n]/.test(after) || (!after.trim() && !separator) ? '' : separator;
  const value = text.slice(0, start) + tag + joined + after.replace(/^[ \t]+/, '');
  return {text: value, caret: start + tag.length + joined.length};
}

// Model words that are not Danbooru tags: quality, score, year and rating words.
export const MODEL_WORDS =
  /^(masterpiece|highres|absurdres|best quality|high quality|good quality|normal quality|low quality|worst quality|newest|recent|mid|early|old|year \d{4}|year\d{4}|score_\d(_up)?|safe|sensitive|nsfw|explicit|general|questionable)$/i;
