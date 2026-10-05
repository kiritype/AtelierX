import { describe, expect, it } from 'vitest';
import { joinMode, splitMode } from './GuidelineSettings';

describe('agent mode head', () => {
  it('reads and writes the guidelines a mode reads along, keeping other lines', () => {
    const text = '---\nname: JSX 만들기\nscope: file\norder: 50\nuses: [jsx.md, platform.md]\nmodel: x\n---\n본문\n';
    const { head, body } = splitMode(text);
    expect(head.uses).toEqual(['jsx.md', 'platform.md']);
    expect(head.rest).toEqual(['model: x']);
    expect(joinMode(head, body)).toBe('---\nname: JSX 만들기\nscope: file\norder: 50\nuses: [jsx.md, platform.md]\nmodel: x\n---\n본문\n');
    expect(joinMode({ ...head, uses: [] }, body)).not.toContain('uses:');
    expect(splitMode('---\nname: a\nuses: jsx.md, "consistency.md"\n---\n').head.uses).toEqual(['jsx.md', 'consistency.md']);
  });
});
