import { describe, expect, it } from 'vitest';
import { replayInputs } from './replay';

type Turn = { text: string; stopped?: boolean; error?: string };

describe('resending inputs', () => {
  const reply = (extra: Partial<Turn> = {}) => async (message: string, history: Turn[]) => [...history, { text: message }, { text: 'answer', ...extra }];

  it('sends every input in order', async () => {
    const { history, sent } = await replayInputs(['a', 'b'], [] as Turn[], reply());
    expect(sent).toBe(2);
    expect(history.map((t) => t.text)).toEqual(['a', 'answer', 'b', 'answer']);
  });

  it('stops after a stopped or failed answer', async () => {
    expect((await replayInputs(['a', 'b', 'c'], [] as Turn[], reply({ stopped: true }))).sent).toBe(1);
    expect((await replayInputs(['a', 'b'], [] as Turn[], reply({ error: 'down' }))).sent).toBe(1);
  });

  it('stops between requests when the screen is left', async () => {
    let left = false;
    const send = async (message: string, history: Turn[]) => {
      left = true;
      return [...history, { text: message }];
    };
    expect((await replayInputs(['a', 'b'], [] as Turn[], send, () => left)).sent).toBe(1);
  });
});
