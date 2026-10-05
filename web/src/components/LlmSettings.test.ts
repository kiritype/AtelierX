import { describe, expect, it } from 'vitest';
import { keyEntryName } from './LlmSettings';

describe('LLM key entries', () => {
  it('reuses the connection entry only while no other connection uses it', () => {
    const providers = { a: { key: 'secret:llm-a' }, b: { key: null } };
    expect(keyEntryName('a', providers, ['llm-a'])).toBe('llm-a');
    // b picked a's key: a new key for a must not change b's.
    expect(keyEntryName('a', { a: { key: 'secret:llm-a' }, b: { key: 'secret:llm-a' } }, ['llm-a'])).toBe('llm-a-2');
  });

  it('does not take over an entry the connection does not use', () => {
    expect(keyEntryName('b', { a: { key: 'secret:llm-b' }, b: { key: null } }, ['llm-b'])).toBe('llm-b-2');
    expect(keyEntryName('c', { c: { key: 'secret:shared' } }, ['llm-c', 'llm-c-2', 'shared'])).toBe('llm-c-3');
  });
});
