import { describe, expect, it } from 'vitest';
import { afterRevisionSave, afterSave, followSelection } from './libraryDraft';

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


describe('afterRevisionSave', () => {
  const sent = { id: 'one', revision: 'old', prompt: ['sent'] };
  const saved = { ...sent, revision: 'new' };
  it('advances the revision while preserving later edits', () => {
    const later = { ...sent, prompt: ['later'] };
    expect(afterRevisionSave(later, sent, saved)).toEqual({ ...later, revision: 'new' });
  });
  it('does not change another selection or an already advanced revision', () => {
    const other = { ...sent, id: 'two' };
    const newer = { ...sent, revision: 'newer' };
    expect(afterRevisionSave(other, sent, saved)).toBe(other);
    expect(afterRevisionSave(newer, sent, saved)).toBe(newer);
  });
  it('adopts the first revision for a newly created item with later edits', () => {
    const fresh: { id: string; prompt: string[]; revision?: string } = { id: 'fresh', prompt: [] };
    const typed = { ...fresh, prompt: ['later'] };
    expect(afterRevisionSave(typed, fresh, { ...fresh, revision: 'first' })).toEqual({ ...typed, revision: 'first' });
  });
});


describe('conflict refresh', () => {
  it('preserves rejected text and stale revision across refreshes until explicit reopen', () => {
    const rejected = { id: 'one', revision: 'old', prompt: ['my unsaved input'] };
    const latest = { id: 'one', revision: 'new', prompt: ['another window'] };
    let draft = followSelection(rejected, 'one', latest);
    expect(draft).toBe(rejected);
    // A retry still uses the rejected base; a list refresh cannot silently authorize an overwrite.
    expect(draft?.revision).toBe('old');
    draft = followSelection(draft, 'one', latest);
    expect(draft).toBe(rejected);
    // Explicitly discarding the draft allows the normal selection loader to take the latest item.
    expect(followSelection(null, 'one', latest)).toBe(latest);
  });
  it('keeps input when a conflicting remote item was deleted', () => {
    const rejected = { id: 'one', revision: 'old', prompt: ['my unsaved input'] };
    expect(followSelection(rejected, 'one', null)).toBe(rejected);
  });
});
