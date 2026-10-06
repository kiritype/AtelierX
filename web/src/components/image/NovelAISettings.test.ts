import { describe, expect, it } from 'vitest';
import { freeForOpus } from './NovelAISettings';

describe('NovelAI free size', () => {
  const free = { pixels: 1024 * 1024, steps: 28 };
  it('is free up to 1024² pixels and 28 steps', () => {
    expect(freeForOpus(832, 1216, 28, free)).toBe(true);
    expect(freeForOpus(1024, 1024, 28, free)).toBe(true);
    expect(freeForOpus(1216, 1216, 28, free)).toBe(false);
    expect(freeForOpus(832, 1216, 29, free)).toBe(false);
  });
});
