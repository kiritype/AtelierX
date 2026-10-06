import { describe, expect, it } from 'vitest';
import { UnsavedRegistry } from './unsaved';

describe('unsaved changes register', () => {
  it('knows which tabs have something unsaved and whether it can be saved from outside', () => {
    const r = new UnsavedRegistry();
    r.set('item:a.md', 'text', { dirty: true, save: async () => true });
    r.set('item:a.md', 'image-design', { dirty: false });
    r.set('settings', 'llm', { dirty: true });
    r.set('image:library', 'item', { dirty: false });
    expect(r.dirtyTabs(['item:a.md', 'settings', 'image:library'])).toEqual(['item:a.md', 'settings']);
    expect(r.canSave('item:a.md')).toBe(true);
    expect(r.canSave('settings')).toBe(false);
    r.set('item:a.md', 'image-design', { dirty: true });
    expect(r.canSave('item:a.md')).toBe(false);
  });

  it('saves every dirty entry and stops at the first failure', async () => {
    const r = new UnsavedRegistry();
    const saved: string[] = [];
    r.set('t', 'one', { dirty: true, save: async () => (saved.push('one'), true) });
    r.set('t', 'two', { dirty: false, save: async () => (saved.push('two'), true) });
    r.set('t', 'three', { dirty: true, save: async () => false });
    expect(await r.save('t')).toBe(false);
    expect(saved).toEqual(['one']);
  });

  it('forgets closed tabs, follows renamed ones and tells listeners', () => {
    const r = new UnsavedRegistry();
    let calls = 0;
    r.subscribe(() => calls++);
    r.set('item:old.md', 'text', { dirty: true });
    r.rename((tab) => (tab === 'item:old.md' ? 'item:new.md' : tab));
    expect(r.dirty('item:new.md') && !r.dirty('item:old.md')).toBe(true);
    r.forget('item:new.md');
    expect(r.dirty('item:new.md')).toBe(false);
    r.set('x', 'k', null);
    expect(calls).toBe(3);
  });
});
