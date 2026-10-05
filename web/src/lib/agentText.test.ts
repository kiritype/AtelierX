import { describe, expect, it } from 'vitest';
import { splitAnswer } from './agentText';

describe('agent answers', () => {
  it('separates prose and closed proposals', () => {
    const parts = splitAnswer('바꿨어요.\n<<<file path="./인물/a.md">>>\n---\nkind: character\n---\n본문\n<<<end>>>\n확인해 주세요.');
    expect(parts.map((p) => p.kind)).toEqual(['text', 'file', 'text']);
    const file = parts[1];
    expect(file).toMatchObject({ path: '인물/a.md', closed: true, n: 1, superseded: false });
    expect(file.kind === 'file' && file.text).toBe('---\nkind: character\n---\n본문\n');
  });

  it('marks a block still being written and numbers paths like the server', () => {
    const parts = splitAnswer('<<<file path="a.md">>>\n1\n<<<end>>>\n<<<file path="b.md">>>\nx\n<<<end>>>\n<<<file path="a.md">>>\n2\n<<<end>>>\n<<<file path="c.md">>>\n쓰는 중');
    const files = parts.filter((p) => p.kind === 'file');
    expect(files.map((f) => f.kind === 'file' && [f.path, f.n, f.superseded, f.closed])).toEqual([
      ['a.md', 1, true, true],
      ['b.md', 2, false, true],
      ['a.md', 1, false, true],
      ['c.md', 3, false, false],
    ]);
  });

  it('leaves code fences in prose alone', () => {
    const parts = splitAnswer('예시:\n```\n<<<end>>>\n```');
    expect(parts).toEqual([{ kind: 'text', text: '예시:\n```\n<<<end>>>\n```' }]);
  });
});
