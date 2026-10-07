import { describe, expect, it } from 'vitest';
import { afterSave, followSelection } from './libraryDraft';

describe('afterSave', () => {
  const sent = { id: 'my02', prompt: ['sent'] };
  const saved = { id: 'my02', prompt: ['sent'], scope: 'global' };

  it('takes the stored version when nothing changed while saving', () => {
    expect(afterSave(sent, sent, saved)).toBe(saved);
  });

  it('keeps an edit made while the save was on its way', () => {
    const typed = { id: 'my02', prompt: ['sent', 'typed later'] };
    expect(afterSave(typed, sent, saved)).toBe(typed);
  });

  it('keeps another item opened while saving', () => {
    const other = { id: 'my01', prompt: ['other'] };
    expect(afterSave(other, sent, saved)).toBe(other);
  });
});

describe('followSelection', () => {
  const stored = { id: 'my02', prompt: ['stored'] };
  const edited = { id: 'my02', prompt: ['edited, not saved'] };

  it('keeps an edit in progress when the list is fetched again', () => {
    expect(followSelection(edited, 'my02', { id: 'my02', prompt: ['fetched again'] })).toBe(edited);
  });

  it('loads the stored item into an empty editor', () => {
    expect(followSelection(null, 'my02', stored)).toBe(stored);
  });

  it('loads the newly selected item', () => {
    const other = { id: 'my01', prompt: ['other'] };
    expect(followSelection(edited, 'my01', other)).toBe(other);
  });

  it('keeps a new item that is not stored yet', () => {
    const fresh = { id: 'my04', prompt: [] };
    expect(followSelection(fresh, 'my04', null)).toBe(fresh);
  });

  it('clears the editor when nothing is selected', () => {
    expect(followSelection(edited, null, null)).toBeNull();
  });
});
