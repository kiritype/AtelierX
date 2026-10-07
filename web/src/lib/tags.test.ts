import { describe, expect, it } from 'vitest';
import { bracketOpen, pasteInto, splitPrompt } from './tags';

describe('pasteInto', () => {
  it('replaces the selection', () => {
    expect(splitPrompt(pasteInto('old tag', 0, 7, 'new one, new two'))).toEqual(['new one', 'new two']);
  });

  it('goes in at the caret', () => {
    expect(pasteInto('ab', 1, 1, 'X, Y')).toBe('aX, Yb');
    expect(pasteInto('ab', 2, 2, ', c')).toBe('ab, c');
  });

  it('keeps out-of-range positions inside the text', () => {
    expect(pasteInto('ab', 5, 9, 'c')).toBe('abc');
  });
});

describe('splitPrompt', () => {
  it('splits at line breaks as well as commas', () => {
    expect(splitPrompt('flat color\nthick outlines\r\ncel shading')).toEqual(['flat color', 'thick outlines', 'cel shading']);
  });

  it('keeps a weighted group whole', () => {
    expect(splitPrompt('masterpiece, (upper body, straight-on:1.4), smile')).toEqual(['masterpiece', '(upper body, straight-on:1.4)', 'smile']);
  });

  it('keeps nested groups and other brackets whole', () => {
    expect(splitPrompt('(a, (b, c:1.2):1.1), [d, e], {f, g}, h')).toEqual(['(a, (b, c:1.2):1.1)', '[d, e]', '{f, g}', 'h']);
  });

  it('does not count escaped brackets', () => {
    expect(splitPrompt('@channel \\(caststation\\), (@n \\(m ohkamotoh\\):1.05), solo')).toEqual([
      '@channel \\(caststation\\)',
      '(@n \\(m ohkamotoh\\):1.05)',
      'solo',
    ]);
  });

  it('trims, drops empty entries and keeps repeats once', () => {
    expect(splitPrompt(' a ,, \n , b, a ,')).toEqual(['a', 'b']);
    expect(splitPrompt('')).toEqual([]);
  });

  it('does not lose text after an unclosed bracket', () => {
    expect(splitPrompt('a, (b, c')).toEqual(['a', '(b, c']);
  });
});

describe('bracketOpen', () => {
  it('is true only while a bracket is open', () => {
    expect(bracketOpen('(upper body,')).toBe(true);
    expect(bracketOpen('(upper body, straight-on:1.4),')).toBe(false);
    expect(bracketOpen('n \\(m,')).toBe(false);
  });
});
