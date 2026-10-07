import { describe, expect, it } from 'vitest';
import { TAB_GROUPS, pickMethod, tabMethods } from './toolMethods';

const features = { tag: ['local'], upscale: ['local', 'novelai'], detail: ['local'], alpha: ['local'], detect: ['local'], inpaint: ['local'] };

describe('image tool methods', () => {
  it('groups every tab once', () => {
    const tabs = TAB_GROUPS.flatMap((g) => g.tabs);
    expect(new Set(tabs).size).toBe(tabs.length);
    expect(tabs.sort()).toEqual(['alpha', 'censor', 'convert', 'inpaint', 'post', 'prompt', 'tag']);
  });

  it('a tab runs with any method of its features; app-only tabs have none', () => {
    expect(tabMethods('post', features)).toEqual(['local', 'novelai']);
    expect(tabMethods('alpha', features)).toEqual(['local']);
    expect(tabMethods('convert', features)).toEqual([]);
    expect(tabMethods('tag', undefined)).toEqual([]);
  });

  it('keeps the last choice only while the tab supports it', () => {
    expect(pickMethod('post', features, { post: 'novelai' })).toBe('novelai');
    expect(pickMethod('alpha', features, { alpha: 'novelai' })).toBe('local');
    expect(pickMethod('inpaint', features, {})).toBe('local');
  });
});
